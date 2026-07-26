# WINDSURF_PROMPT.md
# Contact Center Intelligence Suite — Complete Build Instructions
# READ THIS ENTIRE FILE BEFORE WRITING A SINGLE LINE OF CODE

---

## WHO YOU ARE BUILDING FOR

- **Developer:** Abhishek (Abhi) Yadav, Dallas TX
- **Interview:** Monday 3 PM CST — Ram Agarwal (CEO/CTO), Global Technology Solutions Inc. (GTS)
- **GTS Identity:** Genesys Gold Partner + Google Cloud CCAI Reseller
- **GitHub:** https://github.com/Xaaby
- **Repo to create:** `ccai-quality-agent` (public)
- **Your job:** Write complete, working, production-quality code. Abhi reviews. No snippets. No TODOs. No placeholders in logic.

---

## WHAT YOU ARE BUILDING

A GCP-native AI agent that analyzes customer service call transcripts and does three things:

1. **Scans for PCI-DSS violations** — deterministic regex + Luhn algorithm (NO Gemini for detection)
2. **Scores call quality** — Gemini 2.5 Flash structured output with Pydantic schema, 1-5 integer bands
3. **Generates remediation tickets** — fires conditionally when PCI violation found OR quality score < 3.0

This is a **3-tool Gemini agent** with a tool-calling loop. Not a chatbot. Not a summarizer. A compliance and coaching copilot for contact center QA managers.

**Why it matters to Ram:** Genesys native QA caps at 50 evaluations/agent/day, takes 20 minutes to generate, and cannot analyze timestamp offsets. This agent fills that gap — it's a Genesys complement, not a competitor.

---

## ARCHITECTURE — LOCKED, DO NOT DEVIATE

```
User → Streamlit Frontend (Cloud Run, port 8080)
             ↓ imports directly (no HTTP between processes)
       Tool Logic Layer
             ↓
       Tool 1: audit_pci_compliance()   ← DETERMINISTIC CODE (regex + Luhn)
       Tool 2: score_call_quality()     ← Gemini 2.5 Flash + Pydantic schema
       Tool 3: generate_remediation_ticket() ← conditional logic + SQLite write
             ↓
       SQLite (pipeline_calls.db, baked into Docker image)
             ↓
       Gemini 2.5 Flash (google-genai SDK, tool calling loop)
```

**CRITICAL ARCHITECTURE RULE:** Streamlit is the ONLY public process. It runs on `$PORT` (8080). There is NO separate FastAPI service. Import all tool logic directly into `streamlit_app.py`. This avoids the Cloud Run two-process port conflict that kills demos.

---

## TECH STACK — EVERY VERSION LOCKED

| Component | Choice | Version |
|---|---|---|
| Language | Python | 3.11 |
| Frontend | Streamlit | >=1.35.0 |
| Agent SDK | google-genai (native) | >=0.8.0 |
| LLM | Gemini 2.5 Flash | `gemini-2.5-flash` |
| Data validation | Pydantic | >=2.0 |
| Data store | SQLite | Built-in Python |
| PCI detection | Python re (regex) + custom Luhn | stdlib only |
| Container base | python:3.11-slim | Docker |
| Registry | GCP Artifact Registry | us-central1 |
| Hosting | GCP Cloud Run | us-central1, port 8080 |
| CI/CD | GitHub Actions + Cloud Build | Workload Identity Federation |
| Secrets | GCP Secret Manager | secret: GEMINI_API_KEY |
| Logs | GCP Cloud Logging | structured JSON |

**DO NOT USE:** LangChain, LlamaIndex, Vertex AI SDK, FastAPI (not needed), FAISS, ChromaDB, any vector database.

---

## REPO STRUCTURE — EXACT, NO FILES ADDED OR REMOVED

```
ccai-quality-agent/
├── CLAUDE_CONTEXT.md               ← context for Claude (already written)
├── WINDSURF_PROMPT.md              ← this file
├── .github/
│   └── workflows/
│       └── deploy.yml              ← GitHub Actions CI/CD
├── app/
│   ├── streamlit_app.py            ← main entry point, single public process
│   ├── agent.py                    ← Gemini tool-calling loop
│   ├── schemas.py                  ← ALL Pydantic models (build this first)
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── audit_pci_compliance.py ← Tool 1: deterministic PCI scanner
│   │   ├── score_call_quality.py   ← Tool 2: Gemini structured output scorer
│   │   └── generate_ticket.py      ← Tool 3: conditional ticket generator
│   ├── data/
│   │   ├── generate_transcripts.py ← seeds pipeline_calls.db with 5 transcripts
│   │   └── pipeline_calls.db       ← generated SQLite file (baked into image)
│   └── requirements.txt
├── Dockerfile                      ← single image, port 8080, Streamlit entry
├── docker-compose.yml              ← local dev only
└── README.md                       ← architecture diagram, live URL, demo queries
```

---

## BUILD ORDER — FOLLOW THIS EXACTLY

Build files in this sequence. Do not skip ahead. Each file depends on the previous.

### STEP 1 — schemas.py (BUILD THIS FIRST, EVERYTHING ELSE IMPORTS FROM IT)

This is the most important file. Define every Pydantic model here. All tools and the agent import from this file.

```python
# app/schemas.py
"""
All Pydantic data models for the Contact Center Intelligence Suite.
Every tool input/output is typed here. Gemini response_schema uses these models.
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from enum import IntEnum
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

class SeverityLevel(str):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class TicketStatus(str):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"

class ViolationType(str):
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
    scan_method: str = Field(default="regex+luhn", description="Always regex+luhn — detection is deterministic code, not LLM")


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
```

---

### STEP 2 — generate_transcripts.py

Creates `pipeline_calls.db` with 5 pre-built call transcripts. Seeds both `calls` and `analysis_cache` tables (cache is empty on seed — filled on first analysis run).

**The 5 transcripts — plant these exact violations:**

| ID | Transcript Type | Planted Violation | Expected Ticket |
|---|---|---|---|
| CALL-001 | Clean call | None | No ticket |
| CALL-002 | PCI violation | Agent reads "4532 1234 5678 9010" aloud | CRITICAL ticket |
| CALL-003 | Missing disclosure | No "this call may be recorded" at start | HIGH ticket |
| CALL-004 | Poor quality | Unresolved issue, dead air, no empathy | MEDIUM ticket (quality score < 3.0) |
| CALL-005 | Combined worst case | PCI violation + missing disclosure + poor quality | CRITICAL ticket |

Transcripts must be realistic — 300-500 words each, realistic agent/customer dialogue, timestamps embedded as `[00:01:23]` format at the start of each speaker turn.

**SQLite Schema — exact DDL:**

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS calls (
    call_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    queue_name TEXT NOT NULL,
    transcript_text TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pci_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT NOT NULL,
    violation_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    timestamp_offset_seconds INTEGER NOT NULL,
    transcript_excerpt TEXT NOT NULL,
    remediation_action TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (call_id) REFERENCES calls(call_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS qa_scorecards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    overall_score REAL NOT NULL,
    empathy_score INTEGER NOT NULL,
    resolution_score INTEGER NOT NULL,
    hold_time_score INTEGER NOT NULL,
    escalation_score INTEGER NOT NULL,
    fcr_score INTEGER NOT NULL,
    dead_air_score INTEGER NOT NULL,
    compliance_script_score INTEGER NOT NULL,
    professionalism_score INTEGER NOT NULL,
    sentiment_score INTEGER NOT NULL,
    closing_score INTEGER NOT NULL,
    executive_summary TEXT NOT NULL,
    coaching_priority TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (call_id) REFERENCES calls(call_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS remediation_tickets (
    ticket_id TEXT PRIMARY KEY,
    call_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    trigger_reason TEXT NOT NULL,
    severity_level TEXT NOT NULL,
    primary_issue TEXT NOT NULL,
    supervisor_coaching_script TEXT NOT NULL,
    required_actions TEXT NOT NULL,
    ticket_status TEXT NOT NULL DEFAULT 'OPEN',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (call_id) REFERENCES calls(call_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS analysis_cache (
    call_id TEXT PRIMARY KEY,
    pci_result_json TEXT NOT NULL,
    scorecard_json TEXT,
    ticket_json TEXT,
    analyzed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (call_id) REFERENCES calls(call_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pci_call ON pci_findings(call_id);
CREATE INDEX IF NOT EXISTS idx_scorecards_call ON qa_scorecards(call_id);
CREATE INDEX IF NOT EXISTS idx_tickets_call ON remediation_tickets(call_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON remediation_tickets(ticket_status);
```

---

### STEP 3 — tools/audit_pci_compliance.py

**THIS IS THE MOST IMPORTANT TOOL. ALL DETECTION MUST BE DETERMINISTIC CODE. DO NOT CALL GEMINI FOR DETECTION.**

```python
"""
Tool 1: audit_pci_compliance

CRITICAL: PCI violation detection is 100% deterministic code.
Regex + Luhn algorithm for PAN detection.
Keyword scan for required disclosures.
Gemini is NOT called in this function — not for detection, not for formatting.
This tool must return identical results every single time for the same transcript.
"""
```

**What the scanner must detect:**

1. **PAN (Primary Account Number):** 16-digit sequences matching Visa/MC/Amex/Discover patterns. Apply Luhn algorithm to filter false positives. Flag as `PCI_UNMASKED_PAN`, severity `CRITICAL`.

2. **CVV:** 3-4 digit sequences appearing within 50 characters of words like "security code", "CVV", "CVC", "card verification". Flag as `PCI_UNMASKED_CVV`, severity `CRITICAL`.

3. **Missing recording disclosure:** Scan first 500 characters of transcript for phrases: "this call may be recorded", "call is being recorded", "recorded for quality". If absent, flag as `MISSING_RECORDING_DISCLOSURE`, severity `HIGH`.

4. **Missing refund policy:** Scan for "refund policy", "return policy", "satisfaction guarantee" when context suggests a billing dispute. Flag as `OMITTED_REFUND_POLICY`, severity `MEDIUM`.

**Timestamp offset calculation:**
Character position of violation ÷ 15 (average chars per second of speech) = estimated seconds offset.

**Function signature:**
```python
def audit_pci_compliance(call_id: str, transcript_text: str) -> PCIAuditResult:
```

Returns `PCIAuditResult` from schemas.py. Writes violations to `pci_findings` table in SQLite. Never calls Gemini.

---

### STEP 4 — tools/score_call_quality.py

**Gemini structured output with Pydantic schema. Temperature=0. Thinking DISABLED.**

The 10 quality dimensions and their anchored rubrics:

| Dimension | Score 1 (POOR) | Score 3 (ACCEPTABLE) | Score 5 (EXCELLENT) |
|---|---|---|---|
| Empathy | No acknowledgment of customer frustration | Basic acknowledgment only | Named the emotion, validated it, adapted tone |
| Resolution Rate | Issue unresolved, no next steps | Partial resolution with vague next steps | Issue fully resolved or clear escalation path given |
| Hold Time Rationale | Put on hold with no explanation | Brief explanation given | Explained reason, gave time estimate, checked back |
| Escalation Handling | Transferred without context | Warm transfer with basic context | Full context transferred, customer confirmed understanding |
| First Call Resolution | Required callback or repeat contact | Likely resolved but uncertain | Definitively resolved, customer confirmed |
| Dead Air Management | Multiple silences >10 seconds with no fill | Occasional silence, no filler language | Narrated actions during all silences |
| Compliance Script Adherence | Missing required script elements | Partial script adherence | All required elements delivered verbatim |
| Professionalism | Interrupted customer, used slang | Professional but monotone | Professional, warm, no interruptions |
| Customer Sentiment | Customer ended call frustrated or angry | Customer neutral at close | Customer expressed satisfaction at close |
| Closing Procedure | Call ended without summary or confirmation | Basic close | Summarized resolution, confirmed satisfaction, offered case number |

**Gemini call pattern — EXACT, DO NOT DEVIATE:**

```python
import os
from google import genai
from google.genai import types
from app.schemas import QualityScorecard

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=f"Analyze this call transcript:\n\n{transcript_text}",
    config=types.GenerateContentConfig(
        system_instruction=SCORING_SYSTEM_PROMPT,  # rubric anchors here
        response_mime_type="application/json",
        response_schema=QualityScorecard,
        temperature=0,
        thinking_config=types.ThinkingConfig(thinking_budget=0)
    )
)

scorecard = QualityScorecard.model_validate_json(response.text)
```

**IMPORTANT:** Put rubric anchor text in `system_instruction`, NOT duplicated in the user content. The SDK docs warn against duplication.

**Cache behavior:** Before calling Gemini, check `analysis_cache` table. If `scorecard_json` exists for this `call_id`, return the cached result immediately. Only call Gemini on first analysis.

**Function signature:**
```python
def score_call_quality(call_id: str, transcript_text: str, agent_id: str) -> QualityScorecard:
```

---

### STEP 5 — tools/generate_ticket.py

**Conditional logic — fires only when threshold exceeded. Writes to SQLite.**

**Trigger conditions (either OR both):**
- Any `CRITICAL` or `HIGH` PCI violation found in `PCIAuditResult`
- `overall_score < 3.0` in `QualityScorecard`

**If neither condition met:** Return `None`. No ticket created.

**If triggered:** Call Gemini ONCE to generate the `supervisor_coaching_script` and `required_actions`. Use structured output with `RemediationTicket` schema. Write to `remediation_tickets` table. Write ticket JSON to `analysis_cache`.

**Function signature:**
```python
def generate_remediation_ticket(
    call_id: str,
    agent_id: str,
    pci_result: PCIAuditResult,
    scorecard: QualityScorecard
) -> Optional[RemediationTicket]:
```

---

### STEP 6 — agent.py

**Gemini tool-calling loop. Three tools registered. Manual dispatch.**

This is the orchestration layer. It:
1. Takes a `call_id` and `transcript_text`
2. Always runs Tool 1 (PCI scan) first — deterministic, no Gemini
3. Always runs Tool 2 (quality score) — Gemini structured output
4. Conditionally runs Tool 3 (ticket) — only if threshold exceeded
5. Returns a structured `AgentResult` dict with all three results

**DO NOT use AutomaticFunctionCalling.** Use manual dispatch loop identical to the compliance agent pattern.

**Agent tool declarations — use `parameters_json_schema`, NOT `parameters=`:**

```python
pci_tool = types.FunctionDeclaration(
    name="audit_pci_compliance",
    description="Scans call transcript for PCI-DSS violations using deterministic regex and Luhn algorithm. Returns violations with timestamp offsets.",
    parameters_json_schema={
        "type": "OBJECT",
        "properties": {
            "call_id": {"type": "STRING", "description": "Unique call identifier"},
            "transcript_text": {"type": "STRING", "description": "Full transcript text to scan"}
        },
        "required": ["call_id", "transcript_text"]
    }
)
```

Define all three tool declarations. Wrap in `types.Tool(function_declarations=[...])`.

**Config:**
```python
config = types.GenerateContentConfig(
    system_instruction="You are a Contact Center Compliance Agent. Analyze call transcripts for PCI violations and quality issues. Always run audit_pci_compliance first, then score_call_quality. Generate a remediation ticket if violations are found or quality score is below 3.0.",
    tools=[agent_tool],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    temperature=0
)
```

---

### STEP 7 — streamlit_app.py

**Single page. Clean supervisor dashboard. No sidebar complexity.**

Layout (in order, top to bottom):
1. Header: "Contact Center Compliance & Quality Agent" + tagline "Powered by Gemini 2.5 Flash"
2. Transcript selector: `st.selectbox` showing all 5 pre-built calls by ID + queue name
3. "Run Analysis" button
4. Three result panels side by side using `st.columns(3)`:
   - **Panel 1:** PCI Compliance status (green ✅ / red 🚨) + violations list with timestamp offsets
   - **Panel 2:** Quality Scorecard — overall score + 10 dimension scores as a horizontal bar chart
   - **Panel 3:** Remediation Ticket (if generated) — severity badge + coaching script + required actions
5. Audit trail expander at bottom: raw SQLite rows for the selected call

**Environment variable:** `GEMINI_API_KEY` loaded from Secret Manager via env var in Cloud Run.

**DB path:** `./data/pipeline_calls.db` — baked into the Docker image at build time.

**Import pattern:**
```python
from app.agent import run_analysis
from app.data.generate_transcripts import get_all_calls
```

No HTTP calls. No FastAPI. Everything in-process.

---

### STEP 8 — Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer caching)
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Generate SQLite database at build time
RUN python app/data/generate_transcripts.py

# Expose single port — Cloud Run requirement
EXPOSE 8080

# Single process — Streamlit only
CMD ["streamlit", "run", "app/streamlit_app.py", \
     "--server.port=8080", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
```

---

### STEP 9 — requirements.txt

```
google-genai>=0.8.0
streamlit>=1.35.0
pydantic>=2.0
python-dotenv>=1.0.0
```

No LangChain. No FastAPI. No FAISS. No numpy (not needed). Keep it minimal — smaller image = faster Cloud Run cold start.

---

### STEP 10 — deploy.yml (GitHub Actions)

Pattern is identical to `gcp-devops-compliance-agent` deploy.yml. Replace:
- Service name: `ccai-quality-agent-backend` → `ccai-quality-agent`
- Image name: `ccai-quality-agent`
- Same Workload Identity Federation auth
- Same Artifact Registry push pattern
- Same Cloud Run deploy command

Placeholders to substitute:
- `YOUR_PROJECT_ID`
- `YOUR_WIF_PROVIDER`
- `YOUR_WIF_SERVICE_ACCOUNT`
- Region: `us-central1`

---

### STEP 11 — README.md

Write this last. Must include:
1. Architecture diagram (ASCII or Mermaid)
2. Live URL (fill after deploy)
3. Problem statement: "Genesys native QA: 50 evals/day cap, 20-min delay, no timestamp analysis. This agent fills the gap."
4. The 5 demo queries mapped to which transcript
5. GCP services used and why
6. How to run locally with docker-compose

---

## RULES FOR WINDSURF

1. Build files in the exact order listed above — schemas.py first, always
2. Write complete files — no `# TODO`, no `pass` in production logic, no `...`
3. Every function has type hints and a docstring
4. The PCI scanner NEVER calls Gemini — if you find yourself writing `client.models.generate_content` inside `audit_pci_compliance.py`, STOP and rewrite
5. Always check `analysis_cache` before calling Gemini — cache hit = return cached, no API call
6. Cloud Run gets ONE port (8080) — Streamlit is the only listener
7. SQLite db path must work both locally (`./app/data/pipeline_calls.db`) and in container (`/app/data/pipeline_calls.db`) — use `pathlib.Path(__file__).parent / "pipeline_calls.db"`
8. `GEMINI_API_KEY` always comes from `os.environ.get("GEMINI_API_KEY")` — never hardcoded
9. Thinking must be disabled: `thinking_config=types.ThinkingConfig(thinking_budget=0)` on all Gemini calls
10. Temperature must be 0 on all Gemini calls
11. Do not add services not listed here — no Redis, no Firestore, no Cloud SQL, no Pub/Sub
12. Flag immediately if any requirement will break on GCP free tier

---

## GCP PLACEHOLDERS — SUBSTITUTE BEFORE DEPLOYING

- `YOUR_PROJECT_ID` → GCP project ID (same as compliance agent: `earnest-sight-503519-t5`)
- `YOUR_WIF_PROVIDER` → Workload Identity Federation provider resource name
- `YOUR_WIF_SERVICE_ACCOUNT` → SA email used for WIF
- `LIVE_URL` → assigned after first Cloud Run deploy

---

## DEMO SCRIPT — WHAT ABHI WILL SHOW RAM

Order matters. Do not change it.

1. Select CALL-002 (PCI violation) → Run → PCI panel shows CRITICAL violation with timestamp → Ticket generated
2. Select CALL-001 (clean) → Run → PCI panel shows ✅ Compliant → No ticket → "No false positives"
3. Select CALL-004 (poor quality) → Run → Quality panel shows low scores → MEDIUM coaching ticket
4. Select CALL-005 (combined worst case) → Run → Both PCI + quality fail → CRITICAL ticket with full coaching script
5. Show audit trail expander → SQLite rows visible → "Everything is logged"
6. Re-run CALL-002 → Identical result → "Scores are an audit record — persisted, not recomputed"
