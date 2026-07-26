# CLAUDE_CONTEXT.md
# Contact Center Intelligence Suite — Architecture & Decision Context
# READ THIS FIRST BEFORE DOING ANYTHING IN THIS CHAT

---

## WHO THIS IS FOR

- **Developer:** Abhishek (Abhi) Yadav, Dallas TX
- **Interview:** Monday 3 PM CST — Ram Agarwal (CEO/CTO), Global Technology Solutions Inc. (GTS)
- **GitHub:** https://github.com/Xaaby
- **Repo:** `ccai-quality-agent` (public)
- **Previous project (complete, live):** `gcp-devops-compliance-agent`
  - Backend: `https://gcp-devops-backend-786562162192.us-central1.run.app`
  - Frontend: `https://gcp-devops-frontend-786562162192.us-central1.run.app`
  - GCP project: `earnest-sight-503519-t5`
- **Tooling:** Windsurf (AI IDE) builds code. Claude (claude.ai) designs architecture, reviews code, answers questions.
- **Abhi's coding style:** Primarily vibe-coder — Windsurf writes ~90%, Abhi reviews and can debug live.

---

## THE INTERVIEW CONTEXT

- **Company:** Global Technology Solutions Inc. (GTS) — CCaaS + AI company
- **GTS identity:** Genesys Gold Partner (first Gold Partner ever) + Google Cloud CCAI Reseller + AWS Advanced Partner
- **Products:** OmniAssist (Vertex AI RAG agent assist), OmniBots, OmniRAG, OmniDARS (government courts/administrative law judges), OmniSuite
- **Clients:** Government agencies, courts, hospitals, universities — FedRAMP, NIST, CJIS, SOC 2 compliance
- **Ram Agarwal:** Founder/CEO/CTO — still reads PRs, still in the codebase, Duke Fuqua MBA, values builders, speed-to-value, compliance-aware engineering, citizen outcomes. Asked about agents specifically on the phone call.
- **Aaron Schroeder:** Director of AI — evaluates RAG quality, evaluation frameworks, MCP, context engineering, agentic AI. Second round — not Monday.
- **Becca Randall:** Director of People Operations — cultural fit, communication. On the Monday call but mostly observing.
- **Monday call purpose:** Ram wants to look at GitHub repos, walk through projects live on Teams, see how Abhi thinks. He decides on the spot if Aaron talks to him.

---

## WHY THIS PROJECT — THE POSITIONING

**Genesys native QA has documented operational gaps (from Genesys's own Resource Center):**
- AI-scored evaluations capped at **50 evaluations per agent per day** (raisable to 100/200 only via support ticket)
- Evaluations with AI Scoring take **up to 20 minutes to generate** after call completion
- Native AI Scoring **cannot analyze timestamp offsets, routing metadata, tone, or inferred meaning**
- Confined to objective, transcript-verifiable questions with binary or multiple-choice answers only

**This agent fills those gaps — it is a Genesys complement, not a competitor:**
- No cap on evaluations (processes any volume instantly)
- Results in seconds, not 20 minutes
- Returns **exact timestamp offsets** for violations — something Genesys documents it cannot do
- PCI-DSS violation detection with Luhn algorithm — beyond Genesys's scope

**Ram is a Genesys Gold Partner. "I built the thing that fills the gap your platform documents" is the right pitch.**

---

## WHAT WE ARE BUILDING

A GCP-native AI agent that analyzes customer service call transcripts and:

1. **Scans for PCI-DSS violations** (Tool 1) — deterministic regex + Luhn, no LLM for detection
2. **Scores call quality across 10 dimensions** (Tool 2) — Gemini 2.5 Flash structured output, 1-5 integer bands, cached to SQLite
3. **Generates remediation tickets** (Tool 3) — fires conditionally when PCI violation found OR quality score < 3.0

**This is NOT a chatbot. This is a 3-tool Gemini agent with a tool-calling loop.**

---

## ARCHITECTURE — LOCKED, DO NOT CHANGE WITHOUT ASKING

```
User → Streamlit Frontend (Cloud Run, port 8080)
             ↓ in-process imports (no HTTP between processes)
       app/agent.py (Gemini tool-calling loop)
             ↓
       Tool 1: audit_pci_compliance()   ← regex + Luhn ONLY, zero Gemini
       Tool 2: score_call_quality()     ← Gemini 2.5 Flash + Pydantic schema
       Tool 3: generate_ticket()        ← conditional, fires on threshold
             ↓
       SQLite pipeline_calls.db (baked into Docker image)
             ↓ cache check before every Gemini call
       analysis_cache table (prevents re-scoring same transcript)
```

**CRITICAL RULE: Single process on Cloud Run.** Streamlit is the only public process on port 8080. No FastAPI. No two-port setup. All tool logic imported directly into streamlit_app.py. This is the #1 lesson from Cloud Run deployments — two processes = demo-breaking port conflict.

---

## TECH STACK — EVERY VERSION LOCKED

| Component | Choice | Version/Config |
|---|---|---|
| Language | Python | 3.11 |
| Frontend | Streamlit | >=1.35.0 |
| Agent SDK | google-genai (native) | >=0.8.0 |
| LLM | Gemini 2.5 Flash | `gemini-2.5-flash` |
| Data validation | Pydantic | >=2.0 |
| Data store | SQLite | Built-in Python stdlib |
| PCI detection | Python `re` + Luhn | stdlib only |
| Container | Docker | python:3.11-slim base |
| Registry | GCP Artifact Registry | us-central1 |
| Hosting | GCP Cloud Run | us-central1, port 8080 |
| CI/CD | GitHub Actions + Cloud Build | Workload Identity Federation |
| Secrets | GCP Secret Manager | secret name: GEMINI_API_KEY |
| Logs | GCP Cloud Logging | structured JSON |

**DO NOT USE:** LangChain, LlamaIndex, Vertex AI SDK, FastAPI, FAISS, ChromaDB, any vector database, Redis, Firestore, Cloud SQL, Pub/Sub.

---

## REPO STRUCTURE

```
ccai-quality-agent/
├── CLAUDE_CONTEXT.md               ← this file
├── WINDSURF_PROMPT.md              ← instructions for Windsurf
├── .github/
│   └── workflows/
│       └── deploy.yml              ← GitHub Actions CI/CD
├── app/
│   ├── streamlit_app.py            ← single public process, port 8080
│   ├── agent.py                    ← Gemini tool-calling loop
│   ├── schemas.py                  ← ALL Pydantic models (built first)
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── audit_pci_compliance.py ← Tool 1: deterministic PCI scanner
│   │   ├── score_call_quality.py   ← Tool 2: Gemini structured output
│   │   └── generate_ticket.py      ← Tool 3: conditional ticket generator
│   ├── data/
│   │   ├── generate_transcripts.py ← seeds pipeline_calls.db
│   │   └── pipeline_calls.db       ← SQLite (baked into image at build)
│   └── requirements.txt
├── Dockerfile                      ← single image, Streamlit on 8080
├── docker-compose.yml              ← local dev only
└── README.md
```

---

## THE THREE TOOLS — EXACT SPECIFICATIONS

### Tool 1: audit_pci_compliance (DETERMINISTIC — NO GEMINI)

```python
def audit_pci_compliance(call_id: str, transcript_text: str) -> PCIAuditResult:
```

**Detection logic — ALL deterministic code:**
- PAN: regex for 16-digit sequences + Luhn algorithm validation → `PCI_UNMASKED_PAN`, severity `CRITICAL`
- CVV: 3-4 digits near "security code / CVV / CVC" keywords → `PCI_UNMASKED_CVV`, severity `CRITICAL`
- Missing recording disclosure: scan first 500 chars for required phrases → `MISSING_RECORDING_DISCLOSURE`, severity `HIGH`
- Missing refund policy in billing context → `OMITTED_REFUND_POLICY`, severity `MEDIUM`

**Timestamp offset:** character_position ÷ 15 (avg chars/second of speech)

**This tool NEVER calls Gemini. If you see `client.models.generate_content` in this file, it is wrong.**

### Tool 2: score_call_quality (GEMINI STRUCTURED OUTPUT)

```python
def score_call_quality(call_id: str, transcript_text: str, agent_id: str) -> QualityScorecard:
```

10 dimensions scored 1-5 integer:
- Empathy, Resolution Rate, Hold Time Rationale, Escalation Handling, First Call Resolution
- Dead Air Management, Compliance Script Adherence, Professionalism, Customer Sentiment, Closing Procedure

**Gemini config — EXACT:**
```python
config = types.GenerateContentConfig(
    system_instruction=SCORING_SYSTEM_PROMPT,
    response_mime_type="application/json",
    response_schema=QualityScorecard,
    temperature=0,
    thinking_config=types.ThinkingConfig(thinking_budget=0)
)
```

**Cache rule:** Check `analysis_cache` for existing `scorecard_json` before calling Gemini. Return cached if found.

### Tool 3: generate_ticket (CONDITIONAL)

```python
def generate_remediation_ticket(
    call_id: str,
    agent_id: str,
    pci_result: PCIAuditResult,
    scorecard: QualityScorecard
) -> Optional[RemediationTicket]:
```

Fires when: any CRITICAL or HIGH violation in pci_result OR scorecard.overall_score < 3.0
Returns None when: no violations AND score >= 3.0

---

## GEMINI SDK PATTERN — CONFIRMED CORRECT (DO NOT CHANGE)

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# FunctionDeclaration uses parameters_json_schema (NOT parameters=)
my_fn = types.FunctionDeclaration(
    name="function_name",
    description="...",
    parameters_json_schema={
        "type": "OBJECT",
        "properties": {
            "param_name": {"type": "STRING", "description": "..."}
        },
        "required": ["param_name"]
    }
)

# Disable AFC — required for manual dispatch
config = types.GenerateContentConfig(
    system_instruction="...",
    tools=[types.Tool(function_declarations=[my_fn])],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    temperature=0,
    thinking_config=types.ThinkingConfig(thinking_budget=0)
)

# Manual dispatch loop
contents_history = [types.Content(role="user", parts=[types.Part.from_text(text=user_query)])]
response = client.models.generate_content(model="gemini-2.5-flash", contents=contents_history, config=config)
candidate = response.candidates[0]
contents_history.append(candidate.content)  # MUST append exact candidate.content

for part in candidate.content.parts:
    if part.function_call:
        fn_name = part.function_call.name
        fn_args = dict(part.function_call.args)
        # execute tool, get result
        tool_response_part = types.Part.from_function_response(
            name=fn_name,
            response={"result": tool_result}
        )
        contents_history.append(types.Content(role="user", parts=[tool_response_part]))
```

**Breaking change warnings (learned from Agent 1):**
- DO NOT use `import google.generativeai as genai` (legacy SDK)
- DO NOT use `parameters=` in FunctionDeclaration (use `parameters_json_schema=`)
- DO NOT omit `AutomaticFunctionCallingConfig(disable=True)`
- ALWAYS append `candidate.content` exactly as returned
- ALWAYS set `thinking_budget=0` to disable thinking on all calls

---

## SIMULATED DATA — 5 PRE-BUILT TRANSCRIPTS

| Call ID | Type | Planted Violation | Expected Output |
|---|---|---|---|
| CALL-001 | Clean call | None | ✅ Compliant, no ticket |
| CALL-002 | PCI violation | "4532 1234 5678 9010" spoken aloud | 🚨 CRITICAL ticket |
| CALL-003 | Missing disclosure | No recording notice at start | ⚠️ HIGH ticket |
| CALL-004 | Poor quality | Unresolved, dead air, no empathy | 📋 MEDIUM coaching ticket |
| CALL-005 | Combined worst case | PCI + missing disclosure + poor quality | 🚨 CRITICAL ticket, full coaching script |

Transcripts are 300-500 words, realistic agent/customer dialogue, `[HH:MM:SS]` timestamps per speaker turn.

---

## SQLITE SCHEMA — 5 TABLES

```sql
-- calls: primary call records
-- pci_findings: violations from Tool 1
-- qa_scorecards: dimension scores from Tool 2
-- remediation_tickets: coaching tickets from Tool 3
-- analysis_cache: prevents re-running Gemini on same transcript
```

Full DDL is in WINDSURF_PROMPT.md. Foreign keys enforced. Indexes on call_id in all child tables.

**CACHE BEHAVIOR (critical for demo):**
- First run: all three tools execute, results written to SQLite + analysis_cache
- Subsequent runs of same call_id: read from analysis_cache, return instantly, no Gemini call
- This makes re-runs produce identical results (audit records don't change)
- This is also the correct product behavior — scores are an audit record, not recomputed live

---

## GCP SERVICES USED

| Service | Purpose |
|---|---|
| Cloud Run | Hosts single Streamlit container |
| Artifact Registry | Stores Docker image (repo: ccai-quality-agent) |
| Cloud Build | Triggered by GitHub Actions for automated builds |
| Secret Manager | Stores GEMINI_API_KEY (secret name: GEMINI_API_KEY) |
| Cloud Logging | Structured JSON logs from Streamlit app |
| IAM | Service account: ccai-quality-agent-sa |

**Service Account Roles (least-privilege):**
- roles/run.invoker
- roles/logging.logWriter
- roles/secretmanager.secretAccessor

---

## GCP PLACEHOLDERS — SUBSTITUTE BEFORE DEPLOYING

- `YOUR_PROJECT_ID` → `earnest-sight-503519-t5` (same as Agent 1)
- `YOUR_WIF_PROVIDER` → Workload Identity Federation provider resource name
- `YOUR_WIF_SERVICE_ACCOUNT` → SA email used for WIF
- `LIVE_URL` → assigned after first Cloud Run deploy

---

## KEY DECISIONS MADE — DO NOT REVISIT

1. **Single process on Cloud Run** — Streamlit only, no FastAPI. Cloud Run one-port rule is non-negotiable.
2. **PCI detection is code, not LLM** — regex + Luhn. Deterministic. No exceptions.
3. **Gemini calls are cached** — first run writes to analysis_cache, subsequent runs read from it. This solves drift AND is correct product behavior.
4. **google-genai native SDK** — not LangChain, not Vertex AI SDK. Same as Agent 1.
5. **SQLite in container** — no Cloud SQL, no managed database. Baked into Docker image at build time.
6. **Bundle A over Bundle B** — decided after research from both Claude and Gemini. Reason: Ram is a Genesys Gold Partner and CCaaS CTO. Bundle A speaks directly to his business. Bundle B's determinism advantage does not outweigh the audience fit gap.
7. **Temperature=0 + thinking disabled** — on all Gemini calls to minimize drift.
8. **5 pre-built transcripts** — not user-input. Controls demo variables, eliminates unexpected input risk.

---

## DEMO ORDER — DO NOT CHANGE

1. CALL-002 → PCI violation → CRITICAL ticket → timestamp offset shown
2. CALL-001 → Clean → ✅ Compliant → "No false positives"
3. CALL-004 → Poor quality → MEDIUM coaching ticket
4. CALL-005 → Combined → CRITICAL ticket + full coaching script
5. Audit trail expander → show SQLite rows
6. Re-run CALL-002 → identical result → "Scores are an audit record"

**Lead with deterministic. Explain LLM-based. Never let Ram discover the architecture before you've explained it.**

---

## WHAT TO SAY TO RAM

- **Why this project?** "Genesys native QA caps at 50 evals per agent per day and takes up to 20 minutes. It also can't analyze timestamp offsets — their own docs confirm this. I built the agent that fills that gap as a complement to Genesys, not a replacement."
- **Why three tools?** "The PCI scanner is deterministic code — regex plus Luhn. The quality scorer is Gemini structured output with anchored rubrics. The ticket generator fires conditionally. That conditional reasoning loop is what makes it an agent, not a script."
- **Why consistent results?** "Scores are an audit record. Once a transcript is analyzed, results are persisted to SQLite. Same input in — same result out, because QA records don't change retroactively."
- **Why Gemini?** "GTS resells Google Cloud CCAI. Gemini 2.5 Flash is the same model family powering OmniAssist. Architecture consistency matters — I wouldn't build a Genesys complement on OpenAI."
- **How would this work on real Genesys?** "Replace the SQLite transcripts with Genesys Cloud Conversations API. The agent processes every call automatically post-completion with no daily cap. Violations go into your existing ticketing system via webhook."

---

## RULES FOR CLAUDE IN THIS PROJECT

1. Write complete files, not snippets
2. Flag any GCP placeholder that needs substitution before deploying
3. Keep code clean: type hints, docstrings, consistent formatting — Ram reads PRs
4. Ask before making ANY architectural change
5. If anything exceeds GCP free tier limits, say so immediately
6. Do not suggest adding services not listed (no Firestore, no Cloud SQL, no Redis, no Pub/Sub)
7. The Gemini SDK pattern in this file is confirmed correct — do not change it
8. The PCI scanner must never call Gemini — if you write a version that does, rewrite it
9. The cache pattern is non-negotiable — always check SQLite before calling Gemini
10. Single process on Cloud Run is non-negotiable — if something requires two ports, redesign it

---

## CHAT-COMPASS STATUS

This is a fresh chat starting from the context handoff. Message count resets here.
Previous chat accomplished: full research, bundle evaluation, final decision locked (Bundle A).
This chat purpose: generate files, review code, answer architecture questions, support build.
