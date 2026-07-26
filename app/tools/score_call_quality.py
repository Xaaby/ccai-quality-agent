"""
Tool 2: score_call_quality

Scores a call transcript across 10 quality dimensions using Gemini 2.5 Flash
structured output with a Pydantic response schema.

Cache-first: checks analysis_cache table before calling Gemini.
Temperature=0, thinking disabled. Scores are an audit record — not recomputed.
"""

import os
import json
import sqlite3
import pathlib

from google import genai
from google.genai import types

from app.schemas import QualityScorecard

DB_PATH = pathlib.Path(__file__).parent.parent / "data" / "pipeline_calls.db"

# ============================================================
# GEMINI CLIENT
# ============================================================

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ============================================================
# SCORING SYSTEM PROMPT — rubric anchors for all 10 dimensions
# ============================================================

SCORING_SYSTEM_PROMPT = """
You are a Contact Center Quality Assurance evaluator. Score the provided call transcript
across exactly 10 quality dimensions on an integer scale of 1 to 5.

Use ONLY the anchored rubric below. Do not invent new dimensions. Do not skip any dimension.
Return exactly 10 DimensionScore objects in dimension_scores.

SCORING RUBRIC:

1. Empathy
   1 (POOR)       - No acknowledgment of customer frustration or emotion
   3 (ACCEPTABLE) - Basic acknowledgment only ("I understand")
   5 (EXCELLENT)  - Named the emotion, validated it explicitly, adapted tone accordingly

2. Resolution Rate
   1 (POOR)       - Issue unresolved at end of call, no next steps given
   3 (ACCEPTABLE) - Partial resolution with vague or uncertain next steps
   5 (EXCELLENT)  - Issue fully resolved OR clear, confirmed escalation path given

3. Hold Time Rationale
   1 (POOR)       - Put customer on hold with no explanation
   3 (ACCEPTABLE) - Brief explanation given before hold
   5 (EXCELLENT)  - Explained reason, gave time estimate, checked back during hold

4. Escalation Handling
   1 (POOR)       - Transferred without giving context to next agent or customer
   3 (ACCEPTABLE) - Warm transfer with basic context provided
   5 (EXCELLENT)  - Full context transferred, customer confirmed understanding before transfer

5. First Call Resolution
   1 (POOR)       - Required callback, repeat contact, or escalation clearly needed
   3 (ACCEPTABLE) - Likely resolved but outcome uncertain
   5 (EXCELLENT)  - Definitively resolved in this call; customer confirmed satisfaction

6. Dead Air Management
   1 (POOR)       - Multiple silences >10 seconds with no verbal fill or narration
   3 (ACCEPTABLE) - Occasional silence; no filler language used
   5 (EXCELLENT)  - Narrated actions during all silences ("I'm pulling that up now...")

7. Compliance Script Adherence
   1 (POOR)       - Missing required script elements (e.g., recording disclosure, case number)
   3 (ACCEPTABLE) - Partial script adherence; some elements present
   5 (EXCELLENT)  - All required script elements delivered correctly

8. Professionalism
   1 (POOR)       - Interrupted customer, used slang, or displayed impatience
   3 (ACCEPTABLE) - Professional but monotone; minimal rapport building
   5 (EXCELLENT)  - Professional, warm, no interruptions, built rapport naturally

9. Customer Sentiment
   1 (POOR)       - Customer ended call frustrated, angry, or explicitly dissatisfied
   3 (ACCEPTABLE) - Customer neutral at close; issue addressed but no expressed satisfaction
   5 (EXCELLENT)  - Customer expressed satisfaction, gratitude, or positive sentiment at close

10. Closing Procedure
    1 (POOR)       - Call ended abruptly without summary or next-step confirmation
    3 (ACCEPTABLE) - Basic close; thanked customer
    5 (EXCELLENT)  - Summarized resolution, confirmed customer satisfaction, offered case number

INSTRUCTIONS:
- overall_score must be the arithmetic mean of all 10 dimension scores, rounded to 1 decimal place
- rationale must cite specific transcript evidence (quote or paraphrase)
- transcript_citation should be a direct quote from the transcript when possible
- coaching_priority must be the name of the single lowest-scoring dimension
- executive_summary must be 2-3 sentences for a supervisor audience
""".strip()


# ============================================================
# CACHE FUNCTIONS
# ============================================================

def _get_cached_scorecard(call_id: str) -> QualityScorecard | None:
    """
    Check analysis_cache for an existing scorecard for this call_id.
    Returns deserialized QualityScorecard if found, None otherwise.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        row = conn.execute(
            "SELECT scorecard_json FROM analysis_cache WHERE call_id = ? AND scorecard_json IS NOT NULL",
            (call_id,),
        ).fetchone()
        if row and row[0]:
            return QualityScorecard.model_validate_json(row[0])
        return None
    finally:
        conn.close()


def _write_scorecard_to_cache(call_id: str, scorecard: QualityScorecard) -> None:
    """
    Upsert scorecard_json into analysis_cache for this call_id.
    Creates a new cache row if one does not yet exist.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            """
            INSERT INTO analysis_cache (call_id, pci_result_json, scorecard_json)
            VALUES (?, '{}', ?)
            ON CONFLICT(call_id) DO UPDATE SET
                scorecard_json = excluded.scorecard_json,
                analyzed_at = CURRENT_TIMESTAMP
            """,
            (call_id, scorecard.model_dump_json()),
        )
        conn.commit()
    finally:
        conn.close()


def _write_scorecard_to_db(scorecard: QualityScorecard) -> None:
    """Persist dimension scores to qa_scorecards table for audit trail."""
    scores_by_dim = {d.dimension.lower().replace(" ", "_"): d.score for d in scorecard.dimension_scores}
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO qa_scorecards
                (call_id, agent_id, overall_score,
                 empathy_score, resolution_score, hold_time_score,
                 escalation_score, fcr_score, dead_air_score,
                 compliance_script_score, professionalism_score,
                 sentiment_score, closing_score,
                 executive_summary, coaching_priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scorecard.call_id,
                scorecard.agent_id,
                scorecard.overall_score,
                scores_by_dim.get("empathy", 0),
                scores_by_dim.get("resolution_rate", scores_by_dim.get("resolution", 0)),
                scores_by_dim.get("hold_time_rationale", scores_by_dim.get("hold_time", 0)),
                scores_by_dim.get("escalation_handling", scores_by_dim.get("escalation", 0)),
                scores_by_dim.get("first_call_resolution", scores_by_dim.get("fcr", 0)),
                scores_by_dim.get("dead_air_management", scores_by_dim.get("dead_air", 0)),
                scores_by_dim.get("compliance_script_adherence", scores_by_dim.get("compliance_script", 0)),
                scores_by_dim.get("professionalism", 0),
                scores_by_dim.get("customer_sentiment", scores_by_dim.get("sentiment", 0)),
                scores_by_dim.get("closing_procedure", scores_by_dim.get("closing", 0)),
                scorecard.executive_summary,
                scorecard.coaching_priority,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================
# PUBLIC INTERFACE
# ============================================================

def score_call_quality(call_id: str, transcript_text: str, agent_id: str) -> QualityScorecard:
    """
    Score a call transcript across 10 quality dimensions using Gemini 2.5 Flash.

    Cache-first: returns cached scorecard from analysis_cache without calling Gemini
    if a prior analysis exists for this call_id.

    On first analysis: calls Gemini with structured output (response_schema=QualityScorecard),
    writes result to qa_scorecards table and analysis_cache.

    Args:
        call_id: Unique call identifier matching the calls table.
        transcript_text: Full transcript text to evaluate.
        agent_id: Agent identifier for the scorecard record.

    Returns:
        QualityScorecard with overall_score, 10 DimensionScores, summary, and coaching priority.
    """
    cached = _get_cached_scorecard(call_id)
    if cached is not None:
        return cached

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"Analyze this call transcript:\n\n{transcript_text}",
        config=types.GenerateContentConfig(
            system_instruction=SCORING_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=QualityScorecard,
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    scorecard = QualityScorecard.model_validate_json(response.text)

    # Ensure call_id and agent_id are set correctly (Gemini may not fill these)
    scorecard = scorecard.model_copy(update={"call_id": call_id, "agent_id": agent_id})

    _write_scorecard_to_db(scorecard)
    _write_scorecard_to_cache(call_id, scorecard)

    return scorecard
