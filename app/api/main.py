"""
app/api/main.py

FastAPI backend for ccai-quality-agent.
Exposes two endpoints:
  POST /analyze  — run all three tools against a call transcript
  GET  /health   — liveness probe

Imports directly from existing tool files — no logic is duplicated here.
"""

import sqlite3
import pathlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.schemas import PCIAuditResult, QualityScorecard, RemediationTicket
from app.tools.audit_pci_compliance import audit_pci_compliance
from app.tools.score_call_quality import score_call_quality
from app.tools.generate_ticket import generate_remediation_ticket

DB_PATH = pathlib.Path(__file__).parent.parent / "data" / "pipeline_calls.db"

# ============================================================
# APP SETUP
# ============================================================

app = FastAPI(
    title="CCAI Quality Agent API",
    description="Contact Center AI — PCI audit, quality scoring, remediation tickets",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# REQUEST / RESPONSE MODELS
# ============================================================

class AnalyzeRequest(BaseModel):
    call_id: str
    transcript_text: str
    agent_id: str
    queue_name: str


class AnalyzeResponse(BaseModel):
    call_id: str
    pci_result: PCIAuditResult
    scorecard: QualityScorecard
    ticket: Optional[RemediationTicket]
    cached: bool


# ============================================================
# CACHE HELPERS
# ============================================================

def _upsert_call(call_id: str, agent_id: str, queue_name: str, transcript_text: str) -> None:
    """
    Ensure the call exists in the calls table before tools write to FK-linked tables.
    Uses INSERT OR IGNORE to preserve existing seeded rows and their cached results.
    (INSERT OR REPLACE would cascade-delete pci_findings / qa_scorecards / analysis_cache.)
    """
    estimated_duration = max(1, len(transcript_text) // 15)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO calls
                (call_id, agent_id, queue_name, transcript_text, duration_seconds)
            VALUES (?, ?, ?, ?, ?)
            """,
            (call_id, agent_id, queue_name, transcript_text, estimated_duration),
        )
        conn.commit()
    finally:
        conn.close()


def _get_cached_analysis(call_id: str) -> Optional[tuple[QualityScorecard, Optional[RemediationTicket]]]:
    """
    Check analysis_cache for a completed analysis for this call_id.
    A row is considered complete when scorecard_json IS NOT NULL.

    Returns (QualityScorecard, RemediationTicket | None) if cached, else None.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        row = conn.execute(
            """
            SELECT scorecard_json, ticket_json
            FROM analysis_cache
            WHERE call_id = ? AND scorecard_json IS NOT NULL
            """,
            (call_id,),
        ).fetchone()
        if row is None:
            return None
        scorecard = QualityScorecard.model_validate_json(row[0])
        ticket = RemediationTicket.model_validate_json(row[1]) if row[1] else None
        return scorecard, ticket
    finally:
        conn.close()


# ============================================================
# ENDPOINTS
# ============================================================

@app.get("/health")
def health() -> dict:
    """Liveness probe — returns service status and UTC timestamp."""
    return {
        "status": "ok",
        "service": "ccai-quality-agent-api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    """
    Analyze a call transcript through all three tools.

    Flow:
    1. Upsert call into calls table (INSERT OR IGNORE — preserves cached seeded rows).
    2. Check analysis_cache for a prior complete analysis.
    3. Cache hit  — re-run deterministic PCI scan (no Gemini), deserialize scorecard
                    and ticket from cache. Returns cached=True.
    4. Cache miss — run Tool 1 (PCI), Tool 2 (quality score), Tool 3 (ticket).
                    Returns cached=False.
    """
    try:
        _upsert_call(
            call_id=request.call_id,
            agent_id=request.agent_id,
            queue_name=request.queue_name,
            transcript_text=request.transcript_text,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to upsert call record: {exc}")

    cached_result = _get_cached_analysis(request.call_id)

    if cached_result is not None:
        scorecard, ticket = cached_result
        # PCI scan is 100% deterministic (regex + Luhn, no Gemini).
        # Re-running is safe and avoids deserialising the '{}' placeholder
        # that score_call_quality writes to pci_result_json on first insert.
        try:
            pci_result = audit_pci_compliance(request.call_id, request.transcript_text)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"PCI scan failed: {exc}")

        return AnalyzeResponse(
            call_id=request.call_id,
            pci_result=pci_result,
            scorecard=scorecard,
            ticket=ticket,
            cached=True,
        )

    # Cache miss — run all three tools in sequence.
    try:
        pci_result = audit_pci_compliance(request.call_id, request.transcript_text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PCI audit failed: {exc}")

    try:
        scorecard = score_call_quality(request.call_id, request.transcript_text, request.agent_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Quality scoring failed: {exc}")

    try:
        ticket = generate_remediation_ticket(
            call_id=request.call_id,
            agent_id=request.agent_id,
            pci_result=pci_result,
            scorecard=scorecard,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ticket generation failed: {exc}")

    return AnalyzeResponse(
        call_id=request.call_id,
        pci_result=pci_result,
        scorecard=scorecard,
        ticket=ticket,
        cached=False,
    )
