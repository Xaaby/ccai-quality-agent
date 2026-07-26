"""
Tool 3: generate_remediation_ticket

Fires conditionally when threshold is exceeded:
  - Any CRITICAL or HIGH PCI violation in PCIAuditResult, OR
  - overall_score < 3.0 in QualityScorecard

If neither condition is met, returns None. No ticket created, no Gemini call.

When triggered: calls Gemini once with RemediationTicket response schema to generate
supervisor_coaching_script and required_actions. Writes to remediation_tickets table
and updates analysis_cache.
"""

import os
import json
import uuid
import sqlite3
import pathlib
from datetime import datetime, timezone
from typing import Optional

from google import genai
from google.genai import types

from app.schemas import PCIAuditResult, QualityScorecard, RemediationTicket

DB_PATH = pathlib.Path(__file__).parent.parent / "data" / "pipeline_calls.db"

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ============================================================
# THRESHOLDS
# ============================================================

HIGH_SEVERITY_LEVELS = {"CRITICAL", "HIGH"}
QUALITY_SCORE_THRESHOLD = 3.0

# ============================================================
# TRIGGER EVALUATION
# ============================================================

def _evaluate_triggers(pci_result: PCIAuditResult, scorecard: QualityScorecard) -> tuple[bool, str, str]:
    """
    Evaluate whether ticket generation thresholds are met.

    Returns:
        (should_fire, trigger_reason, severity_level)
        trigger_reason: "PCI_VIOLATION" | "LOW_QUALITY_SCORE" | "BOTH"
        severity_level: highest severity from violations, or "MEDIUM" for quality-only
    """
    has_pci_violation = any(
        v.severity in HIGH_SEVERITY_LEVELS for v in pci_result.violations
    )
    has_low_quality = scorecard.overall_score < QUALITY_SCORE_THRESHOLD

    if not has_pci_violation and not has_low_quality:
        return False, "", ""

    if has_pci_violation and has_low_quality:
        trigger_reason = "BOTH"
    elif has_pci_violation:
        trigger_reason = "PCI_VIOLATION"
    else:
        trigger_reason = "LOW_QUALITY_SCORE"

    # Determine severity level
    severity_priority = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    severity_level = "MEDIUM"  # default for quality-only
    if has_pci_violation:
        for sev in severity_priority:
            if any(v.severity == sev for v in pci_result.violations):
                severity_level = sev
                break

    return True, trigger_reason, severity_level


# ============================================================
# GEMINI PROMPT
# ============================================================

def _build_ticket_prompt(
    call_id: str,
    agent_id: str,
    trigger_reason: str,
    severity_level: str,
    pci_result: PCIAuditResult,
    scorecard: QualityScorecard,
) -> str:
    """Build the user content for the ticket generation Gemini call."""
    pci_summary = ""
    if pci_result.violations:
        violation_lines = "\n".join(
            f"  - [{v.severity}] {v.violation_type} at ~{v.timestamp_offset_seconds}s: \"{v.transcript_excerpt[:80]}\""
            for v in pci_result.violations
            if v.severity in HIGH_SEVERITY_LEVELS
        )
        pci_summary = f"\nPCI Violations Found:\n{violation_lines}"

    low_dims = [
        d for d in scorecard.dimension_scores if d.score <= 2
    ]
    quality_summary = ""
    if low_dims:
        dim_lines = "\n".join(
            f"  - {d.dimension}: {d.score}/5 — {d.rationale}"
            for d in low_dims
        )
        quality_summary = f"\nLow Quality Dimensions (score ≤ 2):\n{dim_lines}"

    return f"""Generate a remediation ticket for the following call analysis results.

Call ID: {call_id}
Agent ID: {agent_id}
Trigger Reason: {trigger_reason}
Severity Level: {severity_level}
Overall Quality Score: {scorecard.overall_score}/5.0
Coaching Priority: {scorecard.coaching_priority}
{pci_summary}
{quality_summary}

Executive Summary: {scorecard.executive_summary}

Generate:
1. ticket_id: use format TKT-{call_id}-<4 random uppercase chars>
2. primary_issue: one concise line describing the main finding
3. supervisor_coaching_script: 3-5 sentences a QA manager reads verbatim in a 1-on-1 with the agent
4. required_actions: ordered list of 3-5 specific, actionable steps the agent must complete
5. ticket_status: "OPEN"
6. created_at: current UTC timestamp in ISO 8601 format
""".strip()


TICKET_SYSTEM_PROMPT = """
You are a Contact Center Quality Assurance manager generating a remediation coaching ticket.
Your output will be read verbatim by a supervisor in a 1-on-1 coaching session.
Be specific, professional, and constructive. Reference the actual violations and scores.
Do not use generic language. Every action item must be concrete and verifiable.
""".strip()


# ============================================================
# SQLITE WRITE
# ============================================================

def _write_ticket_to_db(ticket: RemediationTicket) -> None:
    """Persist the remediation ticket to the remediation_tickets table."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO remediation_tickets
                (ticket_id, call_id, agent_id, trigger_reason, severity_level,
                 primary_issue, supervisor_coaching_script, required_actions,
                 ticket_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket.ticket_id,
                ticket.call_id,
                ticket.agent_id,
                ticket.trigger_reason,
                ticket.severity_level,
                ticket.primary_issue,
                ticket.supervisor_coaching_script,
                json.dumps(ticket.required_actions),
                ticket.ticket_status,
                ticket.created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _write_ticket_to_cache(call_id: str, ticket: RemediationTicket) -> None:
    """Update analysis_cache with ticket_json for this call_id."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            """
            INSERT INTO analysis_cache (call_id, pci_result_json, ticket_json)
            VALUES (?, '{}', ?)
            ON CONFLICT(call_id) DO UPDATE SET
                ticket_json = excluded.ticket_json,
                analyzed_at = CURRENT_TIMESTAMP
            """,
            (call_id, ticket.model_dump_json()),
        )
        conn.commit()
    finally:
        conn.close()


def _get_cached_ticket(call_id: str) -> RemediationTicket | None:
    """Return cached ticket from analysis_cache if it exists."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        row = conn.execute(
            "SELECT ticket_json FROM analysis_cache WHERE call_id = ? AND ticket_json IS NOT NULL",
            (call_id,),
        ).fetchone()
        if row and row[0]:
            return RemediationTicket.model_validate_json(row[0])
        return None
    finally:
        conn.close()


# ============================================================
# PUBLIC INTERFACE
# ============================================================

def generate_remediation_ticket(
    call_id: str,
    agent_id: str,
    pci_result: PCIAuditResult,
    scorecard: QualityScorecard,
) -> Optional[RemediationTicket]:
    """
    Conditionally generate a remediation ticket when thresholds are exceeded.

    Triggers when:
      - Any CRITICAL or HIGH PCI violation found in pci_result, OR
      - scorecard.overall_score < 3.0

    Cache-first: returns cached ticket from analysis_cache if already generated.

    When triggered: calls Gemini once with RemediationTicket structured output,
    writes result to remediation_tickets table and analysis_cache.

    Args:
        call_id: Unique call identifier.
        agent_id: Agent identifier.
        pci_result: Result from audit_pci_compliance tool.
        scorecard: Result from score_call_quality tool.

    Returns:
        RemediationTicket if threshold exceeded, None otherwise.
    """
    should_fire, trigger_reason, severity_level = _evaluate_triggers(pci_result, scorecard)
    if not should_fire:
        return None

    cached = _get_cached_ticket(call_id)
    if cached is not None:
        return cached

    prompt = _build_ticket_prompt(
        call_id=call_id,
        agent_id=agent_id,
        trigger_reason=trigger_reason,
        severity_level=severity_level,
        pci_result=pci_result,
        scorecard=scorecard,
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=TICKET_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=RemediationTicket,
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    ticket = RemediationTicket.model_validate_json(response.text)

    # Enforce correct call_id, agent_id, trigger metadata (Gemini may drift)
    ticket = ticket.model_copy(
        update={
            "call_id": call_id,
            "agent_id": agent_id,
            "trigger_reason": trigger_reason,
            "severity_level": severity_level,
            "ticket_status": "OPEN",
            "created_at": ticket.created_at or datetime.now(timezone.utc).isoformat(),
        }
    )

    _write_ticket_to_db(ticket)
    _write_ticket_to_cache(call_id, ticket)

    return ticket
