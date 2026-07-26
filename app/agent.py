"""
agent.py

Gemini 2.5 Flash tool-calling loop for the Contact Center Intelligence Suite.

Orchestration:
  1. Always runs Tool 1: audit_pci_compliance (deterministic, no Gemini)
  2. Always runs Tool 2: score_call_quality (Gemini structured output)
  3. Conditionally runs Tool 3: generate_remediation_ticket (fires on threshold)

Manual dispatch loop — AutomaticFunctionCalling is disabled.
Uses parameters_json_schema (not parameters=) in FunctionDeclaration.
"""

import os
from typing import Any, Dict, Optional

from google import genai
from google.genai import types

from app.schemas import PCIAuditResult, QualityScorecard, RemediationTicket
from app.tools.audit_pci_compliance import audit_pci_compliance
from app.tools.score_call_quality import score_call_quality
from app.tools.generate_ticket import generate_remediation_ticket
from app.data.generate_transcripts import get_call_by_id

# ============================================================
# GEMINI CLIENT
# ============================================================

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# ============================================================
# TOOL DECLARATIONS
# ============================================================

pci_tool_decl = types.FunctionDeclaration(
    name="audit_pci_compliance",
    description=(
        "Scans a call transcript for PCI-DSS violations using deterministic regex and "
        "Luhn algorithm. Detects unmasked PANs, CVVs, missing recording disclosures, "
        "and missing refund policy disclosures. Returns violations with timestamp offsets."
    ),
    parameters_json_schema={
        "type": "OBJECT",
        "properties": {
            "call_id": {"type": "STRING", "description": "Unique call identifier"},
            "transcript_text": {"type": "STRING", "description": "Full transcript text to scan"},
        },
        "required": ["call_id", "transcript_text"],
    },
)

quality_tool_decl = types.FunctionDeclaration(
    name="score_call_quality",
    description=(
        "Scores a call transcript across 10 quality dimensions (Empathy, Resolution Rate, "
        "Hold Time Rationale, Escalation Handling, First Call Resolution, Dead Air Management, "
        "Compliance Script Adherence, Professionalism, Customer Sentiment, Closing Procedure) "
        "using Gemini 2.5 Flash structured output. Returns integer scores 1-5 per dimension."
    ),
    parameters_json_schema={
        "type": "OBJECT",
        "properties": {
            "call_id": {"type": "STRING", "description": "Unique call identifier"},
            "transcript_text": {"type": "STRING", "description": "Full transcript text to score"},
            "agent_id": {"type": "STRING", "description": "Agent identifier for the scorecard"},
        },
        "required": ["call_id", "transcript_text", "agent_id"],
    },
)

ticket_tool_decl = types.FunctionDeclaration(
    name="generate_remediation_ticket",
    description=(
        "Conditionally generates a remediation ticket. Fires when any CRITICAL or HIGH "
        "PCI violation is found OR the overall quality score is below 3.0. Returns null "
        "if no threshold is exceeded. Writes ticket to SQLite for audit trail."
    ),
    parameters_json_schema={
        "type": "OBJECT",
        "properties": {
            "call_id": {"type": "STRING", "description": "Unique call identifier"},
            "agent_id": {"type": "STRING", "description": "Agent identifier"},
        },
        "required": ["call_id", "agent_id"],
    },
)

agent_tool = types.Tool(
    function_declarations=[pci_tool_decl, quality_tool_decl, ticket_tool_decl]
)

# ============================================================
# AGENT CONFIG
# ============================================================

AGENT_SYSTEM_PROMPT = (
    "You are a Contact Center Compliance and Quality Agent. "
    "Analyze call transcripts for PCI-DSS violations and quality issues. "
    "Always call audit_pci_compliance first, then score_call_quality. "
    "After both tools return results, call generate_remediation_ticket. "
    "The ticket tool will internally decide whether a ticket is needed."
)

agent_config = types.GenerateContentConfig(
    system_instruction=AGENT_SYSTEM_PROMPT,
    tools=[agent_tool],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    temperature=0,
    thinking_config=types.ThinkingConfig(thinking_budget=0),
)

# ============================================================
# TOOL DISPATCH
# ============================================================

def _dispatch_tool(
    fn_name: str,
    fn_args: Dict[str, Any],
    pci_result_store: Dict[str, PCIAuditResult],
    scorecard_store: Dict[str, QualityScorecard],
) -> Any:
    """
    Execute the named tool with the provided arguments.
    Stores intermediate results so the ticket tool can access them.

    Args:
        fn_name: Tool name as declared in FunctionDeclaration.
        fn_args: Arguments passed by the model.
        pci_result_store: Mutable dict to store PCIAuditResult by call_id.
        scorecard_store: Mutable dict to store QualityScorecard by call_id.

    Returns:
        Serializable result dict to return to Gemini via function_response.
    """
    if fn_name == "audit_pci_compliance":
        result = audit_pci_compliance(
            call_id=fn_args["call_id"],
            transcript_text=fn_args["transcript_text"],
        )
        pci_result_store[fn_args["call_id"]] = result
        return result.model_dump()

    if fn_name == "score_call_quality":
        result = score_call_quality(
            call_id=fn_args["call_id"],
            transcript_text=fn_args["transcript_text"],
            agent_id=fn_args["agent_id"],
        )
        scorecard_store[fn_args["call_id"]] = result
        return result.model_dump()

    if fn_name == "generate_remediation_ticket":
        call_id = fn_args["call_id"]
        agent_id = fn_args["agent_id"]
        pci_result = pci_result_store.get(call_id)
        scorecard = scorecard_store.get(call_id)
        if pci_result is None or scorecard is None:
            return {"error": "audit_pci_compliance and score_call_quality must run first"}
        ticket = generate_remediation_ticket(
            call_id=call_id,
            agent_id=agent_id,
            pci_result=pci_result,
            scorecard=scorecard,
        )
        return ticket.model_dump() if ticket else {"ticket": None}

    return {"error": f"Unknown tool: {fn_name}"}


# ============================================================
# PUBLIC INTERFACE
# ============================================================

def run_analysis(call_id: str) -> Dict[str, Any]:
    """
    Run the full 3-tool analysis pipeline for a call.

    Orchestration order:
      1. audit_pci_compliance — deterministic, always runs
      2. score_call_quality — Gemini structured output, cache-first
      3. generate_remediation_ticket — conditional, fires on threshold

    The Gemini agent decides which tools to call via the tool-calling loop.
    All tool calls are dispatched manually (AFC disabled).

    Args:
        call_id: Identifier for the call to analyze (must exist in calls table).

    Returns:
        Dict with keys: call_id, agent_id, pci_result, scorecard, ticket, error (optional).
    """
    call_record = get_call_by_id(call_id)
    if call_record is None:
        return {"call_id": call_id, "error": f"Call {call_id} not found in database."}

    transcript_text = call_record["transcript_text"]
    agent_id = call_record["agent_id"]

    user_query = (
        f"Analyze call {call_id} for agent {agent_id}. "
        f"Run audit_pci_compliance, then score_call_quality, then generate_remediation_ticket.\n\n"
        f"Transcript:\n{transcript_text}"
    )

    contents_history = [
        types.Content(role="user", parts=[types.Part.from_text(text=user_query)])
    ]

    pci_result_store: Dict[str, PCIAuditResult] = {}
    scorecard_store: Dict[str, QualityScorecard] = {}
    final_pci: Optional[PCIAuditResult] = None
    final_scorecard: Optional[QualityScorecard] = None
    final_ticket: Optional[RemediationTicket] = None

    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents_history,
            config=agent_config,
        )

        candidate = response.candidates[0]
        contents_history.append(candidate.content)

        has_function_call = any(
            part.function_call is not None for part in candidate.content.parts
        )

        if not has_function_call:
            break

        function_response_parts = []
        for part in candidate.content.parts:
            if part.function_call is None:
                continue

            fn_name = part.function_call.name
            fn_args = dict(part.function_call.args)

            tool_result = _dispatch_tool(fn_name, fn_args, pci_result_store, scorecard_store)

            # Capture final results
            if fn_name == "audit_pci_compliance":
                final_pci = pci_result_store.get(fn_args.get("call_id", call_id))
            elif fn_name == "score_call_quality":
                final_scorecard = scorecard_store.get(fn_args.get("call_id", call_id))
            elif fn_name == "generate_remediation_ticket":
                if tool_result and "ticket" not in tool_result:
                    try:
                        final_ticket = RemediationTicket(**tool_result)
                    except Exception:
                        final_ticket = None

            function_response_parts.append(
                types.Part.from_function_response(
                    name=fn_name,
                    response={"result": tool_result},
                )
            )

        contents_history.append(
            types.Content(role="user", parts=function_response_parts)
        )

    return {
        "call_id": call_id,
        "agent_id": agent_id,
        "pci_result": final_pci,
        "scorecard": final_scorecard,
        "ticket": final_ticket,
    }
