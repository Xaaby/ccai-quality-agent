# CCAI Quality Agent

A GCP-native AI agent that analyzes customer service call transcripts for PCI-DSS violations, scores call quality across 10 dimensions, and generates supervisor coaching tickets — deployed on Cloud Run with Gemini 2.5 Flash.

**Live demo:** [https://ccai-quality-agent-786562162192.us-central1.run.app](https://ccai-quality-agent-786562162162.us-central1.run.app)

**Stack:** Python 3.11 · Streamlit · Gemini 2.5 Flash · Pydantic · SQLite · Cloud Run · GitHub Actions

---

## Why This Exists

Genesys native QA has documented operational gaps — 50 evaluations per agent per day cap, up to 20 minutes to generate results after call completion, and no ability to return timestamp offsets for violations. This agent fills those gaps as a **complement to Genesys, not a replacement.**

| Capability | Genesys Native QA | This Agent |
|---|---|---|
| Daily eval cap | 50/agent/day | No cap |
| Time to results | Up to 20 minutes | Seconds |
| Timestamp offsets on violations | ✗ Not supported | ✓ Exact offset returned |
| PCI PAN/CVV detection | ✗ Out of scope | ✓ Luhn-validated, deterministic |
| Scores as audit records | Recomputed | Cached — same input, same output, always |

---

## Architecture

```
User → Streamlit Frontend (Cloud Run, port 8080)
             │  in-process imports (no HTTP between processes)
             ▼
       app/agent.py  ←  Gemini 2.5 Flash tool-calling loop (AFC disabled)
             │
       ┌─────┴───────────────────────────────────────────┐
       │                                                  │
       ▼                                                  ▼
Tool 1: audit_pci_compliance()           Tool 2: score_call_quality()
  · regex + Luhn ONLY                      · Gemini 2.5 Flash
  · zero Gemini calls                      · Pydantic response_schema
  · deterministic output                   · 10 dimensions, 1–5 integer
  · timestamp offsets                      · cache-first (no re-scoring)
       │                                                  │
       └──────────────────┬───────────────────────────────┘
                          ▼
               Tool 3: generate_remediation_ticket()
                 · fires when CRITICAL/HIGH violation OR score < 3.0
                 · returns None when clean (no false-positive tickets)
                 · writes to SQLite for audit trail
                          │
                          ▼
               SQLite: pipeline_calls.db
               Tables: calls · pci_findings · qa_scorecards
                       remediation_tickets · analysis_cache
```

**Single process on Cloud Run** — Streamlit is the only listener on port 8080. All tool logic is imported directly. No FastAPI, no two-port setup.

---

## The Three Tools

### Tool 1 — `audit_pci_compliance()` · Deterministic · Zero Gemini

Detection logic is pure Python — no LLM involved:

- **PAN detection:** 16-digit regex + Luhn algorithm validation → `PCI_UNMASKED_PAN` (CRITICAL)
- **CVV detection:** 3–4 digits near security code keywords → `PCI_UNMASKED_CVV` (CRITICAL)
- **Missing recording disclosure:** Scans first 500 chars → `MISSING_RECORDING_DISCLOSURE` (HIGH)
- **Missing refund policy:** Billing context check → `OMITTED_REFUND_POLICY` (MEDIUM)

Timestamp offset: `character_position ÷ 15` (avg chars/second of speech).

This tool **never calls Gemini.** Deterministic detection is the right design choice for PCI — an LLM getting 99.9% accuracy on card numbers is not good enough when the 0.1% is a compliance breach.

### Tool 2 — `score_call_quality()` · Gemini Structured Output

10 dimensions scored 1–5 integer via Pydantic `response_schema`:

Empathy · Resolution Rate · Hold Time Rationale · Escalation Handling · First Call Resolution · Dead Air Management · Compliance Script Adherence · Professionalism · Customer Sentiment · Closing Procedure

**Cache rule:** Checks `analysis_cache` for existing scorecard before calling Gemini. Returns cached result if found — scores are an audit record and do not change retroactively.

### Tool 3 — `generate_remediation_ticket()` · Conditional

Fires when: any CRITICAL or HIGH PCI violation **OR** `overall_score < 3.0`

Returns `None` when: no violations AND score ≥ 3.0

This conditional firing is what makes the agent reason rather than script — it evaluates both tool outputs before deciding whether a ticket is warranted.

---

## Demo Script

Run these calls in order:

| Step | Call ID | What to show |
|---|---|---|
| 1 | CALL-002 | PCI violation → CRITICAL ticket with exact timestamp offset |
| 2 | CALL-001 | Clean call → ✅ Compliant → "No false positives" |
| 3 | CALL-004 | Poor quality → MEDIUM coaching ticket, low dimension scores |
| 4 | CALL-005 | PCI + poor quality combined → CRITICAL ticket + full coaching script |
| 5 | Audit trail | Expand SQLite section → "Everything is logged" |
| 6 | Re-run CALL-002 | Identical result → "Scores are an audit record, not recomputed" |

---

## Pre-built Transcripts

| Call ID | Type | Planted Violation | Expected Output |
|---|---|---|---|
| CALL-001 | Clean | None | ✅ Compliant, no ticket |
| CALL-002 | PCI violation | Card number spoken aloud | 🚨 CRITICAL ticket + timestamp offset |
| CALL-003 | Missing disclosure | No recording notice at call start | ⚠️ HIGH ticket |
| CALL-004 | Poor quality | Unresolved, dead air, no empathy | 📋 MEDIUM coaching ticket |
| CALL-005 | Combined worst case | PCI + missing disclosure + poor quality | 🚨 CRITICAL ticket + coaching script |

---

## GCP Services

| Service | Purpose |
|---|---|
| Cloud Run | Single Streamlit container, port 8080 |
| Artifact Registry | Docker image (`ccai-quality-agent` repo, us-central1) |
| Secret Manager | `GEMINI_API_KEY` — never hardcoded |
| Cloud Build | Triggered by GitHub Actions via Workload Identity Federation |
| Cloud Logging | Structured JSON logs from the Streamlit process |
| IAM | `ccai-quality-agent-sa` with least-privilege roles only |

**Service account roles:**
- `roles/run.invoker`
- `roles/logging.logWriter`
- `roles/secretmanager.secretAccessor`

---

## Repository Structure

```
ccai-quality-agent/
├── app/
│   ├── streamlit_app.py             ← single public process, port 8080
│   ├── agent.py                     ← Gemini tool-calling loop (AFC disabled)
│   ├── schemas.py                   ← all Pydantic models
│   ├── tools/
│   │   ├── audit_pci_compliance.py  ← Tool 1: regex + Luhn, zero Gemini
│   │   ├── score_call_quality.py    ← Tool 2: Gemini structured output + cache
│   │   └── generate_ticket.py       ← Tool 3: conditional ticket
│   ├── data/
│   │   ├── generate_transcripts.py  ← seeds pipeline_calls.db
│   │   └── pipeline_calls.db        ← SQLite baked into Docker image
│   └── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .github/workflows/deploy.yml
└── README.md
```

---

## Local Development

```bash
# Clone repo and install dependencies
git clone https://github.com/Xaaby/ccai-quality-agent.git
cd ccai-quality-agent
pip install -r app/requirements.txt

# Seed the database
python app/data/generate_transcripts.py

# Run
GEMINI_API_KEY=your_key_here streamlit run app/streamlit_app.py --server.port 8080
```

Or with Docker:

```bash
export GEMINI_API_KEY=your_key_here
docker-compose up --build
# App at http://localhost:8080
```

---

## How This Connects to Real Genesys

In production, replace the SQLite transcripts with the **Genesys Cloud Conversations API** — every call is analyzed automatically post-completion with no daily cap. Violation tickets route to your existing ticketing system via webhook. The agent, tools, and scoring rubric are unchanged.

The architecture is identical to what a Genesys Gold Partner would deploy as a QA complement layer on top of native AI Scoring.
