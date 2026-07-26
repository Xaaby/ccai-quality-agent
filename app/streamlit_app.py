"""
streamlit_app.py

Contact Center Compliance & Quality Agent — Supervisor Dashboard.
Single public process on Cloud Run port 8080. No FastAPI. All tool logic in-process.
"""

import sys
import os
import json
import pathlib

# Ensure project root is on sys.path so 'from app.X import Y' works
# regardless of how Streamlit resolves the script directory.
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from app.agent import run_analysis
from app.data.generate_transcripts import get_all_calls, get_audit_trail

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="CCAI Quality Agent",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
# CUSTOM CSS
# ============================================================

st.markdown(
    """
    <style>
    .metric-card {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
        border-left: 4px solid #dee2e6;
    }
    .metric-card.critical { border-left-color: #dc3545; background: #fff5f5; }
    .metric-card.high { border-left-color: #fd7e14; background: #fff8f0; }
    .metric-card.medium { border-left-color: #ffc107; background: #fffdf0; }
    .metric-card.low { border-left-color: #28a745; background: #f0fff4; }
    .badge-critical { background:#dc3545; color:white; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }
    .badge-high { background:#fd7e14; color:white; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }
    .badge-medium { background:#ffc107; color:#333; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }
    .badge-low { background:#28a745; color:white; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold; }
    .score-bar-bg { background:#e9ecef; border-radius:4px; height:12px; margin:4px 0; }
    .score-bar { height:12px; border-radius:4px; }
    .section-header { font-size:14px; font-weight:600; color:#495057; text-transform:uppercase; letter-spacing:0.5px; margin:12px 0 8px 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# HEADER
# ============================================================

st.markdown("## 🎯 Contact Center Compliance & Quality Agent")
st.markdown(
    "<span style='color:#6c757d;font-size:14px;'>Powered by Gemini 2.5 Flash &nbsp;·&nbsp; "
    "PCI-DSS Scanner &nbsp;·&nbsp; 10-Dimension Quality Scoring &nbsp;·&nbsp; "
    "Automated Remediation Tickets</span>",
    unsafe_allow_html=True,
)
st.divider()

# ============================================================
# CALL SELECTOR
# ============================================================

calls = get_all_calls()
if not calls:
    st.error("No calls found in database. Run `python app/data/generate_transcripts.py` to seed data.")
    st.stop()

call_options = {
    f"{c['call_id']} — {c['queue_name']} ({c['agent_id']}, {c['duration_seconds']}s)": c["call_id"]
    for c in calls
}

col_select, col_btn = st.columns([4, 1])
with col_select:
    selected_label = st.selectbox(
        "Select a call to analyze:",
        options=list(call_options.keys()),
        label_visibility="collapsed",
    )
with col_btn:
    run_clicked = st.button("▶ Run Analysis", type="primary", use_container_width=True)

selected_call_id = call_options[selected_label]

# ============================================================
# SESSION STATE — persist results across reruns
# ============================================================

if "results" not in st.session_state:
    st.session_state.results = {}

# ============================================================
# RUN ANALYSIS
# ============================================================

if run_clicked:
    with st.spinner(f"Analyzing {selected_call_id}..."):
        result = run_analysis(selected_call_id)
        st.session_state.results[selected_call_id] = result

result = st.session_state.results.get(selected_call_id)

if result is None:
    st.info("Select a call and click **▶ Run Analysis** to begin.")
    st.stop()

if "error" in result and result["error"]:
    st.error(f"Analysis error: {result['error']}")
    st.stop()

pci_result = result.get("pci_result")
scorecard = result.get("scorecard")
ticket = result.get("ticket")

# ============================================================
# THREE-PANEL RESULTS
# ============================================================

col1, col2, col3 = st.columns(3, gap="medium")

# ----------------------------------------------------------
# PANEL 1 — PCI Compliance
# ----------------------------------------------------------
with col1:
    st.markdown("### PCI Compliance")
    if pci_result is None:
        st.warning("PCI scan not yet complete.")
    elif pci_result.is_fully_compliant:
        st.success("✅ Fully Compliant")
        st.markdown(
            f"**Scan method:** `{pci_result.scan_method}` &nbsp; **Violations:** 0",
            unsafe_allow_html=True,
        )
    else:
        st.error(f"🚨 {pci_result.total_violations} Violation(s) Found")
        for v in pci_result.violations:
            sev_lower = v.severity.lower()
            st.markdown(
                f"""
                <div class='metric-card {sev_lower}'>
                  <span class='badge-{sev_lower}'>{v.severity}</span>
                  &nbsp;<strong>{v.violation_type}</strong><br/>
                  <small>⏱ ~{v.timestamp_offset_seconds}s offset</small><br/>
                  <small><em>"{v.transcript_excerpt[:100]}..."</em></small><br/>
                  <small>📋 {v.remediation_action[:120]}...</small>
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown(
            f"<small style='color:#6c757d;'>Scan method: {pci_result.scan_method}</small>",
            unsafe_allow_html=True,
        )

# ----------------------------------------------------------
# PANEL 2 — Quality Scorecard
# ----------------------------------------------------------
with col2:
    st.markdown("### Quality Scorecard")
    if scorecard is None:
        st.warning("Quality scoring not yet complete.")
    else:
        score = scorecard.overall_score
        if score >= 4.0:
            score_color = "#28a745"
            score_label = "GOOD–EXCELLENT"
        elif score >= 3.0:
            score_color = "#ffc107"
            score_label = "ACCEPTABLE"
        else:
            score_color = "#dc3545"
            score_label = "POOR"

        st.markdown(
            f"<h2 style='margin:0;color:{score_color};'>{score:.1f} <span style='font-size:16px;color:#6c757d;'>/ 5.0 — {score_label}</span></h2>",
            unsafe_allow_html=True,
        )
        st.markdown(f"*{scorecard.executive_summary}*")
        st.markdown(
            f"<div class='section-header'>🎯 Coaching Priority: {scorecard.coaching_priority}</div>",
            unsafe_allow_html=True,
        )
        st.markdown("<div class='section-header'>Dimension Scores</div>", unsafe_allow_html=True)

        for dim in scorecard.dimension_scores:
            bar_pct = int((dim.score / 5) * 100)
            if dim.score <= 2:
                bar_color = "#dc3545"
            elif dim.score == 3:
                bar_color = "#ffc107"
            else:
                bar_color = "#28a745"
            st.markdown(
                f"""
                <div style='margin-bottom:6px;'>
                  <div style='display:flex;justify-content:space-between;font-size:13px;'>
                    <span>{dim.dimension}</span><span><strong>{dim.score}/5</strong></span>
                  </div>
                  <div class='score-bar-bg'>
                    <div class='score-bar' style='width:{bar_pct}%;background:{bar_color};'></div>
                  </div>
                  <div style='font-size:11px;color:#6c757d;'>{dim.rationale}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

# ----------------------------------------------------------
# PANEL 3 — Remediation Ticket
# ----------------------------------------------------------
with col3:
    st.markdown("### Remediation Ticket")
    if ticket is None:
        st.success("✅ No ticket required")
        st.markdown(
            "No CRITICAL/HIGH PCI violations detected and quality score ≥ 3.0. "
            "No coaching action needed at this time."
        )
    else:
        sev = ticket.severity_level.lower()
        st.markdown(
            f"<span class='badge-{sev}'>{ticket.severity_level}</span> "
            f"&nbsp;<code>{ticket.ticket_id}</code>",
            unsafe_allow_html=True,
        )
        st.markdown(f"**Trigger:** `{ticket.trigger_reason}`")
        st.markdown(f"**Primary Issue:** {ticket.primary_issue}")
        st.markdown("<div class='section-header'>Supervisor Coaching Script</div>", unsafe_allow_html=True)
        st.info(ticket.supervisor_coaching_script)
        st.markdown("<div class='section-header'>Required Actions</div>", unsafe_allow_html=True)
        if isinstance(ticket.required_actions, list):
            for i, action in enumerate(ticket.required_actions, 1):
                st.markdown(f"{i}. {action}")
        else:
            try:
                actions = json.loads(ticket.required_actions)
                for i, action in enumerate(actions, 1):
                    st.markdown(f"{i}. {action}")
            except (json.JSONDecodeError, TypeError):
                st.markdown(str(ticket.required_actions))
        st.markdown(
            f"<small style='color:#6c757d;'>Status: {ticket.ticket_status} &nbsp;·&nbsp; Created: {ticket.created_at}</small>",
            unsafe_allow_html=True,
        )

# ============================================================
# AUDIT TRAIL EXPANDER
# ============================================================

st.divider()
with st.expander("🗃️ Audit Trail — Raw SQLite Records", expanded=False):
    audit = get_audit_trail(selected_call_id)

    st.markdown("**PCI Findings Table**")
    if audit["pci_findings"]:
        st.json(audit["pci_findings"])
    else:
        st.markdown("*No PCI findings recorded yet.*")

    st.markdown("**QA Scorecards Table**")
    if audit["qa_scorecards"]:
        st.json(audit["qa_scorecards"])
    else:
        st.markdown("*No scorecard recorded yet.*")

    st.markdown("**Remediation Tickets Table**")
    if audit["remediation_tickets"]:
        st.json(audit["remediation_tickets"])
    else:
        st.markdown("*No remediation ticket recorded yet.*")

    st.markdown("**Analysis Cache**")
    if audit["cache_entry"]:
        st.json(audit["cache_entry"])
    else:
        st.markdown("*No cache entry yet — run analysis first.*")
