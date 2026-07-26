"""
Tool 1: audit_pci_compliance

CRITICAL: PCI violation detection is 100% deterministic code.
Regex + Luhn algorithm for PAN detection.
Keyword scan for required disclosures.
Gemini is NOT called in this function — not for detection, not for formatting.
This tool must return identical results every single time for the same transcript.
"""

import re
import sqlite3
import pathlib
from typing import List

from app.schemas import ComplianceViolation, PCIAuditResult

DB_PATH = pathlib.Path(__file__).parent.parent / "data" / "pipeline_calls.db"

# ============================================================
# REGEX PATTERNS
# ============================================================

# 16-digit card number: digits optionally separated by spaces or dashes
PAN_PATTERN = re.compile(
    r"\b(?:4[0-9]{3}|5[1-5][0-9]{2}|2[2-7][0-9]{2}|6(?:011|5[0-9]{2})|3[47][0-9]{2})"
    r"[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}\b"
)

# CVV: 3-4 digits near card verification keyword within 50 chars
CVV_KEYWORD_PATTERN = re.compile(
    r"(?:security\s+code|cvv|cvc|card\s+verification)",
    re.IGNORECASE,
)
CVV_DIGIT_PATTERN = re.compile(r"\b\d{3,4}\b")

# Recording disclosure phrases (checked in first 500 chars)
RECORDING_PHRASES = [
    "this call may be recorded",
    "call is being recorded",
    "recorded for quality",
    "recorded for training",
    "may be monitored or recorded",
]

# Refund policy indicators
REFUND_PHRASES = [
    "refund policy",
    "return policy",
    "satisfaction guarantee",
]

# Billing dispute context keywords
BILLING_CONTEXT_KEYWORDS = [
    "refund",
    "credit",
    "charged",
    "overcharged",
    "billing",
    "dispute",
    "reimburs",
    "money back",
]

# Chars per second of speech — used for timestamp offset estimation
CHARS_PER_SECOND = 15


# ============================================================
# LUHN ALGORITHM
# ============================================================

def _luhn_check(number: str) -> bool:
    """
    Validate a digit string using the Luhn algorithm.
    Returns True if the number passes the Luhn check.
    """
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13:
        return False
    total = 0
    reverse_digits = digits[::-1]
    for i, digit in enumerate(reverse_digits):
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


# ============================================================
# DETECTION FUNCTIONS
# ============================================================

def _detect_pan_violations(transcript: str) -> List[ComplianceViolation]:
    """
    Detect unmasked Primary Account Numbers using regex + Luhn algorithm.
    Returns a list of ComplianceViolation objects for each confirmed PAN.
    """
    violations: List[ComplianceViolation] = []
    for match in PAN_PATTERN.finditer(transcript):
        raw = match.group()
        digits_only = re.sub(r"[\s\-]", "", raw)
        if not _luhn_check(digits_only):
            continue  # Luhn filter: not a real card number
        char_pos = match.start()
        timestamp_offset = char_pos // CHARS_PER_SECOND
        violations.append(
            ComplianceViolation(
                violation_type="PCI_UNMASKED_PAN",
                severity="CRITICAL",
                timestamp_offset_seconds=timestamp_offset,
                transcript_excerpt=raw,
                remediation_action=(
                    "Immediately stop reading card numbers aloud. "
                    "Use DTMF tone capture or secure IVR for PAN collection. "
                    "Retrain agent on PCI-DSS Section 3.3: prohibition on storing/displaying full PAN."
                ),
            )
        )
    return violations


def _detect_cvv_violations(transcript: str) -> List[ComplianceViolation]:
    """
    Detect unmasked CVV/CVC values by finding 3-4 digit sequences
    within 50 characters of a card verification keyword.
    """
    violations: List[ComplianceViolation] = []
    for kw_match in CVV_KEYWORD_PATTERN.finditer(transcript):
        window_start = max(0, kw_match.start() - 10)
        window_end = min(len(transcript), kw_match.end() + 50)
        window = transcript[window_start:window_end]
        for digit_match in CVV_DIGIT_PATTERN.finditer(window):
            raw_cvv = digit_match.group()
            char_pos = window_start + digit_match.start()
            timestamp_offset = char_pos // CHARS_PER_SECOND
            excerpt = transcript[max(0, char_pos - 20): char_pos + len(raw_cvv) + 20]
            violations.append(
                ComplianceViolation(
                    violation_type="PCI_UNMASKED_CVV",
                    severity="CRITICAL",
                    timestamp_offset_seconds=timestamp_offset,
                    transcript_excerpt=excerpt.strip(),
                    remediation_action=(
                        "Never request or repeat CVV values verbally. "
                        "CVV must be collected via secure DTMF or encrypted web form only. "
                        "PCI-DSS Section 3.2.1 prohibits storage of CVV after authorization."
                    ),
                )
            )
            break  # one CVV violation per keyword match
    return violations


def _detect_missing_recording_disclosure(transcript: str) -> List[ComplianceViolation]:
    """
    Check the first 500 characters of transcript for a recording disclosure phrase.
    Flags a violation if none is found.
    """
    opening = transcript[:500].lower()
    for phrase in RECORDING_PHRASES:
        if phrase in opening:
            return []
    return [
        ComplianceViolation(
            violation_type="MISSING_RECORDING_DISCLOSURE",
            severity="HIGH",
            timestamp_offset_seconds=0,
            transcript_excerpt=transcript[:200].strip(),
            remediation_action=(
                "Agent must state the recording disclosure within the first 15 seconds of every call. "
                "Required script: 'This call may be recorded for quality and training purposes.' "
                "Add to opening script and verify adherence weekly."
            ),
        )
    ]


def _detect_missing_refund_policy(transcript: str) -> List[ComplianceViolation]:
    """
    Detect omission of refund/return policy in a billing dispute context.
    Only flags if the call contains billing dispute keywords but no refund policy mention.
    """
    lower = transcript.lower()
    is_billing_dispute = any(kw in lower for kw in BILLING_CONTEXT_KEYWORDS)
    if not is_billing_dispute:
        return []
    has_refund_mention = any(phrase in lower for phrase in REFUND_PHRASES)
    if has_refund_mention:
        return []
    # Find first billing context keyword for excerpt
    char_pos = 0
    for kw in BILLING_CONTEXT_KEYWORDS:
        idx = lower.find(kw)
        if idx != -1:
            char_pos = idx
            break
    timestamp_offset = char_pos // CHARS_PER_SECOND
    excerpt = transcript[max(0, char_pos - 20): char_pos + 80].strip()
    return [
        ComplianceViolation(
            violation_type="OMITTED_REFUND_POLICY",
            severity="MEDIUM",
            timestamp_offset_seconds=timestamp_offset,
            transcript_excerpt=excerpt,
            remediation_action=(
                "When handling billing disputes, agents must communicate the refund/return policy. "
                "Required: state timeline, eligibility criteria, and confirmation process. "
                "Update call guide to include refund policy disclosure checklist item."
            ),
        )
    ]


# ============================================================
# SQLITE WRITE
# ============================================================

def _write_violations_to_db(call_id: str, violations: List[ComplianceViolation]) -> None:
    """Persist each violation to the pci_findings table."""
    if not violations:
        return
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executemany(
            """
            INSERT OR IGNORE INTO pci_findings
                (call_id, violation_type, severity, timestamp_offset_seconds,
                 transcript_excerpt, remediation_action)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    call_id,
                    v.violation_type,
                    v.severity,
                    v.timestamp_offset_seconds,
                    v.transcript_excerpt,
                    v.remediation_action,
                )
                for v in violations
            ],
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================
# PUBLIC INTERFACE
# ============================================================

def audit_pci_compliance(call_id: str, transcript_text: str) -> PCIAuditResult:
    """
    Scan a call transcript for PCI-DSS violations using deterministic code only.

    Detection methods:
    - PAN: regex pattern for major card networks + Luhn algorithm validation
    - CVV: 3-4 digit sequences near card verification keywords
    - Missing recording disclosure: keyword scan of first 500 characters
    - Missing refund policy: billing dispute context + absence of policy mention

    No Gemini call is made. Returns identical results for identical input.

    Args:
        call_id: Unique identifier for the call record.
        transcript_text: Full transcript text to scan.

    Returns:
        PCIAuditResult with all violations found and compliance status.
    """
    violations: List[ComplianceViolation] = []

    violations.extend(_detect_pan_violations(transcript_text))
    violations.extend(_detect_cvv_violations(transcript_text))
    violations.extend(_detect_missing_recording_disclosure(transcript_text))
    violations.extend(_detect_missing_refund_policy(transcript_text))

    high_or_critical = {"CRITICAL", "HIGH"}
    is_compliant = not any(v.severity in high_or_critical for v in violations)

    _write_violations_to_db(call_id, violations)

    return PCIAuditResult(
        call_id=call_id,
        is_fully_compliant=is_compliant,
        total_violations=len(violations),
        violations=violations,
        scan_method="regex+luhn",
    )
