# app/schemas.py
"""
All Pydantic data models for the Contact Center Intelligence Suite.
Every tool input/output is typed here. Gemini response_schema uses these models.
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from enum import IntEnum, Enum
from datetime import datetime


# ============================================================
# ENUMS — used for Gemini response_schema to constrain output
# ============================================================

class QualityBand(IntEnum):
    """1-5 integer band for all quality dimension scores."""
    POOR = 1
    BELOW_AVERAGE = 2
    ACCEPTABLE = 3
    GOOD = 4
    EXCELLENT = 5


class SeverityLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"


class ViolationType(str, Enum):
    PCI_UNMASKED_PAN = "PCI_UNMASKED_PAN"
    PCI_UNMASKED_CVV = "PCI_UNMASKED_CVV"
    MISSING_RECORDING_DISCLOSURE = "MISSING_RECORDING_DISCLOSURE"
    OMITTED_REFUND_POLICY = "OMITTED_REFUND_POLICY"
    MISSING_ESCALATION_DISCLOSURE = "MISSING_ESCALATION_DISCLOSURE"


# ============================================================
# TOOL 1 — PCI Compliance Audit Schemas
# ============================================================

class ComplianceViolation(BaseModel):
    violation_type: str = Field(
        description="One of: PCI_UNMASKED_PAN, PCI_UNMASKED_CVV, MISSING_RECORDING_DISCLOSURE, OMITTED_REFUND_POLICY, MISSING_ESCALATION_DISCLOSURE"
    )
    severity: str = Field(
        description="One of: CRITICAL, HIGH, MEDIUM, LOW"
    )
    timestamp_offset_seconds: int = Field(
        description="Estimated position in seconds where violation occurs, calculated from character position"
    )
    transcript_excerpt: str = Field(
        description="The exact substring from the transcript that triggered this violation"
    )
    remediation_action: str = Field(
        description="Specific action required to remediate this violation"
    )


class PCIAuditResult(BaseModel):
    call_id: str
    is_fully_compliant: bool = Field(
        description="True only if zero CRITICAL or HIGH violations found"
    )
    total_violations: int
    violations: List[ComplianceViolation]
    scan_method: str = Field(
        default="regex+luhn",
        description="Always regex+luhn — detection is deterministic code, not LLM"
    )


# ============================================================
# TOOL 2 — Quality Scorecard Schemas
# ============================================================

class DimensionScore(BaseModel):
    dimension: str = Field(
        description="Quality dimension name"
    )
    score: int = Field(
        ge=1, le=5,
        description="Integer score 1 (poor) to 5 (excellent). Use anchored rubric in system prompt."
    )
    rationale: str = Field(
        description="One sentence justification citing specific transcript evidence"
    )
    transcript_citation: Optional[str] = Field(
        default=None,
        description="Direct quote from transcript supporting this score"
    )


class QualityScorecard(BaseModel):
    call_id: str
    agent_id: str
    overall_score: float = Field(
        description="Average of all 10 dimension scores, rounded to 1 decimal"
    )
    dimension_scores: List[DimensionScore] = Field(
        description="Exactly 10 dimension scores — one per dimension"
    )
    executive_summary: str = Field(
        description="2-3 sentence summary of agent performance for supervisor"
    )
    coaching_priority: str = Field(
        description="The single most important dimension to improve, by name"
    )


# ============================================================
# TOOL 3 — Remediation Ticket Schemas
# ============================================================

class RemediationTicket(BaseModel):
    ticket_id: str
    call_id: str
    agent_id: str
    trigger_reason: str = Field(
        description="Why ticket was generated: PCI_VIOLATION, LOW_QUALITY_SCORE, or BOTH"
    )
    severity_level: str = Field(
        description="Highest severity from audit result, or MEDIUM if quality-only trigger"
    )
    primary_issue: str = Field(
        description="One-line description of the primary finding"
    )
    supervisor_coaching_script: str = Field(
        description="3-5 sentence coaching script for the QA manager to read verbatim in a 1-on-1"
    )
    required_actions: List[str] = Field(
        description="Ordered list of specific actions the agent must take"
    )
    ticket_status: str = Field(default="OPEN")
    created_at: str


# ============================================================
# CALL RECORD — stored in SQLite
# ============================================================

class CallRecord(BaseModel):
    call_id: str
    agent_id: str
    queue_name: str
    transcript_text: str
    duration_seconds: int
    created_at: str


class AnalysisCache(BaseModel):
    """Stored in SQLite after first analysis. Returned on re-runs without calling Gemini."""
    call_id: str
    pci_result_json: str      # JSON string of PCIAuditResult
    scorecard_json: str       # JSON string of QualityScorecard
    ticket_json: Optional[str]  # JSON string of RemediationTicket, null if not triggered
    analyzed_at: str
