# ccai-quality-agent

**Contact Center Compliance & Quality Agent** — A GCP-native AI agent that analyzes customer service call transcripts for PCI-DSS violations, scores call quality across 10 dimensions, and generates supervisor coaching tickets.

> **Genesys native QA: 50 evals/day cap, 20-min delay, no timestamp analysis. This agent fills the gap.**

Live URL: *(assigned after first Cloud Run deploy)*

---

## Architecture

```
User → Streamlit Frontend (Cloud Run, port 8080)
             │  in-process imports (no HTTP between processes)
             ▼
       app/agent.py  ←  Gemini 2.5 Flash tool-calling loop (AFC disabled)
             │
       ┌─────┴──────────────────────────────────────────┐
       │                                                 │
       ▼                                                 ▼
Tool 1: audit_pci_compliance()          Tool 2: score_call_quality()
  · regex + Luhn ONLY                     · Gemini 2.5 Flash
  · zero Gemini calls                     · Pydantic response_schema
  · deterministic output                  · 10 dimensions, 1-5 integer
  · timestamp offsets                     · cache-first (no re-scoring)
       │                                                 │
       └─────────────────┬───────────────────────────────┘
                         ▼
              Tool 3: generate_remediation_ticket()
                · fires when CRITICAL/HIGH violation OR score < 3.0
                · Gemini structured output coaching script
                · writes to SQLite for audit trail
                         │
                         ▼
              SQLite: pipeline_calls.db
              (baked into Docker image at build time)
              Tables: calls, pci_findings, qa_scorecards,
                      remediation_tickets, analysis_cache
```

**Why Genesys Gold Partners care:**
- No 50 eval/day cap — processes any volume instantly
- Results in seconds vs. up to 20 minutes for Genesys native AI Scoring
- Returns **exact timestamp offsets** for violations — Genesys native QA cannot do this
- PCI-DSS PAN/CVV detection with Luhn algorithm — beyond Genesys's native scope
- Cache layer ensures scores are audit records: same input → same output, always

---

## Tech Stack

| Component | Choice | Version |
|---|---|---|
| Language | Python | 3.11 |
| Frontend | Streamlit | >=1.35.0 |
| Agent SDK | google-genai (native) | >=0.8.0 |
| LLM | Gemini 2.5 Flash | `gemini-2.5-flash` |
| Data validation | Pydantic | >=2.0 |
| Data store | SQLite | Python stdlib |
| PCI detection | Python `re` + Luhn | stdlib only |
| Container | Docker | python:3.11-slim |
| Registry | GCP Artifact Registry | us-central1 |
| Hosting | GCP Cloud Run | us-central1, port 8080 |
| CI/CD | GitHub Actions + WIF | On push to `main` |
| Secrets | GCP Secret Manager | `GEMINI_API_KEY` |

---

## Demo Script

Run these in order — matches the interview demo flow:

| Step | Call | What to show |
|---|---|---|
| 1 | **CALL-002** | PCI violation → CRITICAL ticket with timestamp offset |
| 2 | **CALL-001** | Clean call → ✅ Compliant → "No false positives" |
| 3 | **CALL-004** | Poor quality → MEDIUM coaching ticket, low dim scores |
| 4 | **CALL-005** | PCI + poor quality → CRITICAL ticket + full coaching script |
| 5 | Audit trail | Expand SQLite section → "Everything is logged" |
| 6 | Re-run CALL-002 | Identical result → "Scores are an audit record" |

### Pre-built Transcripts

| Call ID | Type | Planted Violation | Expected Output |
|---|---|---|---|
| CALL-001 | Clean | None | ✅ Compliant, no ticket |
| CALL-002 | PCI violation | `4532 1234 5678 9010` spoken aloud | 🚨 CRITICAL ticket |
| CALL-003 | Missing disclosure | No recording notice at start | ⚠️ HIGH ticket |
| CALL-004 | Poor quality | Unresolved, dead air, no empathy | 📋 MEDIUM coaching ticket |
| CALL-005 | Combined worst case | PCI + missing disclosure + poor quality | 🚨 CRITICAL ticket |

---

## GCP Services Used

| Service | Purpose |
|---|---|
| **Cloud Run** | Hosts single Streamlit container (one port, one process) |
| **Artifact Registry** | Stores Docker image (`ccai-quality-agent` repo) |
| **Cloud Build** | Triggered by GitHub Actions via Workload Identity Federation |
| **Secret Manager** | Stores `GEMINI_API_KEY` — never hardcoded |
| **Cloud Logging** | Structured JSON logs from Streamlit process |
| **IAM** | SA `ccai-quality-agent-sa` with least-privilege roles |

---

## Local Development

### Prerequisites
- Python 3.11
- Docker Desktop
- `GEMINI_API_KEY` in your environment

### Run with Docker Compose

```bash
# Clone and enter repo
git clone https://github.com/Xaaby/ccai-quality-agent.git
cd ccai-quality-agent

# Set your API key
export GEMINI_API_KEY=your_key_here

# Build and run (seeds SQLite at build time)
docker-compose up --build
```

App available at: http://localhost:8080

### Run locally without Docker

```bash
cd ccai-quality-agent

# Install dependencies
pip install -r app/requirements.txt

# Seed the database
python app/data/generate_transcripts.py

# Run Streamlit
GEMINI_API_KEY=your_key_here streamlit run app/streamlit_app.py --server.port 8080
```

---

## Deployment (GCP)

### One-time setup (before first deploy)

```bash
# Create Artifact Registry repo
gcloud artifacts repositories create ccai-quality-agent \
  --repository-format=docker \
  --location=us-central1

# Create Secret Manager secret
echo -n "your_gemini_api_key" | \
  gcloud secrets create GEMINI_API_KEY --data-file=-

# Configure Workload Identity Federation
# (follow GCP docs — substitute YOUR_WIF_PROVIDER and YOUR_WIF_SERVICE_ACCOUNT in deploy.yml)
```

### Automated deploy

Push to `main` → GitHub Actions builds image → pushes to Artifact Registry → deploys to Cloud Run.

Substitute in `.github/workflows/deploy.yml`:
- `YOUR_WIF_PROVIDER` → your WIF provider resource name
- `YOUR_WIF_SERVICE_ACCOUNT` → your service account email

---

## Project Structure

```
ccai-quality-agent/
├── app/
│   ├── __init__.py
│   ├── streamlit_app.py          ← single public process, port 8080
│   ├── agent.py                  ← Gemini tool-calling loop (AFC disabled)
│   ├── schemas.py                ← all Pydantic models
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── audit_pci_compliance.py  ← Tool 1: regex + Luhn, zero Gemini
│   │   ├── score_call_quality.py    ← Tool 2: Gemini structured output
│   │   └── generate_ticket.py       ← Tool 3: conditional ticket
│   ├── data/
│   │   ├── __init__.py
│   │   ├── generate_transcripts.py  ← seeds pipeline_calls.db
│   │   └── pipeline_calls.db        ← SQLite (baked into image)
│   └── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .github/workflows/deploy.yml
└── README.md
```
