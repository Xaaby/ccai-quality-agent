"""
generate_transcripts.py

Seeds pipeline_calls.db with 5 pre-built call transcripts.
Run directly (python app/data/generate_transcripts.py) or at Docker build time.
Also provides get_all_calls() for the Streamlit frontend.
"""

import sqlite3
import pathlib
from typing import List, Dict, Any

DB_PATH = pathlib.Path(__file__).parent / "pipeline_calls.db"

# ============================================================
# DDL
# ============================================================

DDL = """
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
"""

# ============================================================
# TRANSCRIPTS
# ============================================================

TRANSCRIPTS: List[Dict[str, Any]] = [
    {
        "call_id": "CALL-001",
        "agent_id": "AGENT-042",
        "queue_name": "Billing Support",
        "duration_seconds": 312,
        "transcript_text": """[00:00:02] Agent: Thank you for calling Horizon Communications. This call may be recorded for quality and training purposes. My name is Sarah, how can I assist you today?
[00:00:10] Customer: Hi Sarah, I'm calling about my bill. I was charged twice for my internet service this month and I'd like to get that sorted out.
[00:00:18] Agent: I completely understand how frustrating that must be — seeing a double charge is never something you want on your statement. Let me pull up your account right now. Can I get your account number or the phone number associated with the account?
[00:00:30] Customer: Sure, it's 214-555-0198.
[00:00:34] Agent: Perfect, thank you. I'm just pulling that up now — give me just a moment while I access your billing history.
[00:00:45] Agent: Okay, I can see your account here. And you're absolutely right — I do see two separate charges for internet service on the 3rd and the 5th of this month. The second charge appears to be a system error on our end. I sincerely apologize for that.
[00:01:01] Customer: Okay, so can you reverse the duplicate?
[00:01:04] Agent: Absolutely. I'm going to initiate a credit of $79.99 back to your account right now. This will appear on your next statement, but if you were charged to a credit card, it typically posts within 3 to 5 business days. I'll also flag your account so our billing team reviews it to make sure this doesn't happen again.
[00:01:25] Customer: That's great, thank you. Will I get a confirmation?
[00:01:28] Agent: Yes — you'll receive a confirmation email to the address on file within the next 30 minutes. Is there anything else I can help you with today?
[00:01:36] Customer: No, that covers it. Thanks Sarah, I appreciate how quickly you handled that.
[00:01:41] Agent: My pleasure! I'm glad we could get that resolved for you. Your case number for this credit is CR-20240315-8821. Don't hesitate to call back if you have any other questions. Have a wonderful day!
[00:01:52] Customer: You too, bye.
[00:01:54] Agent: Goodbye!""",
    },
    {
        "call_id": "CALL-002",
        "agent_id": "AGENT-017",
        "queue_name": "Payment Processing",
        "duration_seconds": 428,
        "transcript_text": """[00:00:03] Agent: Thank you for calling Horizon Communications. This call may be recorded for quality and training purposes. My name is Marcus. How can I help you today?
[00:00:12] Customer: Hi Marcus. I need to make a payment on my account. I've been getting disconnection notices and I want to make sure this gets applied today.
[00:00:20] Agent: Of course, I can absolutely help you process that payment right now. Let me bring up your account. Can I get your account number?
[00:00:27] Customer: Yes, it's 7782940.
[00:00:31] Agent: Got it, thank you. I see the account here. Your current balance due is $234.87. Would you like to pay that in full today?
[00:00:40] Customer: Yes, the full amount. I'll use my Visa card.
[00:00:43] Agent: Great. Go ahead and give me your card number.
[00:00:46] Customer: It's 4532 1234 5678 9010.
[00:00:52] Agent: And the expiration date?
[00:00:54] Customer: 09/27.
[00:00:56] Agent: And the security code on the back?
[00:00:58] Customer: 341.
[00:01:00] Agent: Perfect. And the billing zip code?
[00:01:02] Customer: 75201.
[00:01:04] Agent: Great, let me process that now. Okay, your payment of $234.87 has been applied successfully. You'll receive a confirmation email shortly and your service will remain active.
[00:01:18] Customer: Oh thank goodness. I was worried about getting cut off.
[00:01:22] Agent: You're all set. Is there anything else I can help you with?
[00:01:25] Customer: No that's it. Thanks Marcus.
[00:01:27] Agent: Thank you for calling Horizon Communications. Have a great day!
[00:01:30] Customer: You too.""",
    },
    {
        "call_id": "CALL-003",
        "agent_id": "AGENT-031",
        "queue_name": "Technical Support",
        "duration_seconds": 356,
        "transcript_text": """[00:00:02] Agent: Horizon Communications technical support, this is David speaking. What seems to be the issue today?
[00:00:08] Customer: Hi, my internet has been going in and out for the past two days. I work from home and this is really impacting my ability to do my job.
[00:00:17] Agent: I understand. Can I get your account number?
[00:00:20] Customer: It's 3345-889-21.
[00:00:24] Agent: Okay I've got your account. Let me run a remote diagnostic on your modem.
[00:00:29] Customer: Sure. Is this going to take long? I have a meeting in 20 minutes.
[00:00:33] Agent: Shouldn't take too long. Running it now.
[00:01:02] Agent: Okay the diagnostic shows some signal instability on your line. There are packet losses happening periodically, which explains the drops you're seeing.
[00:01:12] Customer: So what does that mean for me? Is this something you can fix remotely?
[00:01:17] Agent: I can push a reset to your modem which sometimes clears signal issues. Let me try that.
[00:01:23] Customer: Okay.
[00:01:55] Agent: Alright, I've pushed the reset. Your modem will restart — it takes about two minutes. Can you check after it comes back online and see if things look more stable?
[00:02:05] Customer: Okay, it's restarting now... okay it's back. Let me run a speed test... Yeah the speeds look better actually.
[00:02:22] Agent: Great. The signal instability may have been caused by line noise. If the issue comes back within 48 hours, call us back and we'll escalate to a field technician visit.
[00:02:33] Customer: Okay, and if that happens will there be a charge for the visit?
[00:02:37] Agent: It depends on whether the issue is on our infrastructure or on your side of the demarcation point. I can't say for certain right now.
[00:02:46] Customer: That's a bit vague. I'd like to know before someone comes out.
[00:02:50] Agent: I understand. Just call back if it happens and we'll go over it at that point.
[00:02:56] Customer: Alright. Fine. Thanks.
[00:02:59] Agent: Thank you for calling. Goodbye.""",
    },
    {
        "call_id": "CALL-004",
        "agent_id": "AGENT-055",
        "queue_name": "Customer Retention",
        "duration_seconds": 487,
        "transcript_text": """[00:00:05] Agent: This call may be recorded for quality. Horizon Communications, this is Tyler.
[00:00:10] Customer: Hi Tyler, I'm calling because I want to cancel my service. I've been a customer for six years and honestly I'm just fed up.
[00:00:18] Agent: Okay. What's the reason for canceling?
[00:00:21] Customer: The price keeps going up. My bill was $89 when I started and now it's $147. Nobody told me it was going to jump this much.
[00:00:30] Agent: Yeah prices do change. Let me see what's on your account.
[00:00:35] Customer: I mean, I feel like six years of loyalty should count for something. I've never missed a payment.
[00:00:41] Agent: I see that. Okay so looking at your account, you've got the standard internet and cable bundle.
[00:00:48] Customer: Right, and like I said it went up $58 from when I signed up. That's a lot.
[00:00:54] Agent: I can see if there's a promotional rate.
[00:00:57] Customer: I already called last month and someone said they'd look into it and call me back. Nobody ever did.
[00:01:04] Agent: Okay. I don't see a note about that.
[00:01:09] Customer: Well it happened. Can you help me today or not?
[00:01:13] Agent: Let me put you on hold while I check what retention offers are available.
[00:01:17] Customer: Okay.
[00:02:41] Agent: Thanks for holding. So I found a promotional bundle — internet plus cable for $119 per month for 12 months.
[00:02:49] Customer: That's still $30 more than I was paying originally.
[00:02:52] Agent: Right, but it's a savings versus what you're paying now.
[00:02:56] Customer: I guess. Is there anything better than that?
[00:02:59] Agent: That's what I have.
[00:03:03] Customer: What happens after the 12 months?
[00:03:06] Agent: It would go back to the standard rate.
[00:03:09] Customer: So I'd be in the same position again next year.
[00:03:12] Agent: Potentially, yeah.
[00:03:15] Customer: I'm going to think about it. This isn't really the resolution I was hoping for.
[00:03:21] Agent: Okay. Do you want me to note that on the account?
[00:03:24] Customer: I guess. I'm pretty disappointed honestly.
[00:03:28] Agent: Alright. Well let us know what you decide. Is there anything else?
[00:03:33] Customer: No. Bye.
[00:03:35] Agent: Goodbye.""",
    },
    {
        "call_id": "CALL-005",
        "agent_id": "AGENT-009",
        "queue_name": "Payment Processing",
        "duration_seconds": 521,
        "transcript_text": """[00:00:04] Agent: Horizon Communications, this is Kevin, how can I help you?
[00:00:09] Customer: Hi, I need to pay my bill and I also want to talk about a refund I was promised.
[00:00:15] Agent: Sure. Account number?
[00:00:17] Customer: 9912-443-77.
[00:00:21] Agent: Got it. Balance is $312.50. Go ahead with your payment?
[00:00:26] Customer: Yes, I'll use my card. Number is 4929 0000 0000 1000.
[00:00:34] Agent: Expiration?
[00:00:36] Customer: 11/26.
[00:00:38] Agent: Security code?
[00:00:40] Customer: 782.
[00:00:42] Agent: Zip?
[00:00:43] Customer: 90210.
[00:00:46] Agent: Okay processing. Payment went through. Now about that refund?
[00:00:51] Customer: Yes, I was overcharged two months ago. Someone told me I'd get a credit but it never showed up. I've been calling about this for weeks.
[00:01:01] Agent: Let me look at the account... I see a note here from six weeks ago mentioning an adjustment but I don't see the credit applied.
[00:01:11] Customer: Right, that's the problem. It's $45.
[00:01:14] Agent: I'm going to have to escalate this to our billing adjustments team.
[00:01:18] Customer: I've already been escalated twice. Can't you just apply the credit?
[00:01:23] Agent: I don't have the access level to apply credits over $25.
[00:01:27] Customer: Then transfer me to someone who does.
[00:01:30] Agent: I can transfer you, but the wait time over there is usually pretty long right now.
[00:01:36] Customer: I've been dealing with this for six weeks. I'll wait.
[00:01:40] Agent: Okay I'll transfer you.
[00:01:43] Customer: Wait — before you do, what's the name of the team you're transferring me to? Last time no one knew where I was transferred and I got disconnected.
[00:01:52] Agent: Billing adjustments.
[00:01:54] Customer: And you're giving them context about my issue, right? You're not just cold-transferring me?
[00:01:59] Agent: I'll leave a note.
[00:02:02] Customer: A note? Not a warm transfer?
[00:02:05] Agent: I'm not able to do a warm transfer from this queue.
[00:02:09] Customer: This is really frustrating. Every time I call I have to start over from scratch.
[00:02:14] Agent: I understand. Do you want me to transfer?
[00:02:17] Customer: Fine. Go ahead.
[00:02:19] Agent: Transferring now. Thank you for your patience.
[00:02:23] Customer: I wouldn't call it patience at this point.""",
    },
]


# ============================================================
# DATABASE FUNCTIONS
# ============================================================

def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with foreign keys enabled."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes from DDL."""
    conn.executescript(DDL)
    conn.commit()


def seed_transcripts(conn: sqlite3.Connection) -> None:
    """Insert the 5 pre-built transcripts if they don't already exist."""
    cursor = conn.cursor()
    for t in TRANSCRIPTS:
        cursor.execute(
            """
            INSERT OR IGNORE INTO calls
                (call_id, agent_id, queue_name, transcript_text, duration_seconds)
            VALUES (?, ?, ?, ?, ?)
            """,
            (t["call_id"], t["agent_id"], t["queue_name"], t["transcript_text"], t["duration_seconds"]),
        )
    conn.commit()


def get_all_calls() -> List[Dict[str, Any]]:
    """Return all call records as a list of dicts. Used by Streamlit selector."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT call_id, agent_id, queue_name, duration_seconds, created_at FROM calls ORDER BY call_id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_call_by_id(call_id: str) -> Dict[str, Any] | None:
    """Return a single call record by call_id, or None if not found."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM calls WHERE call_id = ?", (call_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_audit_trail(call_id: str) -> Dict[str, Any]:
    """Return all SQLite rows for a call_id for the audit trail expander."""
    conn = get_connection()
    try:
        pci = [dict(r) for r in conn.execute(
            "SELECT * FROM pci_findings WHERE call_id = ?", (call_id,)
        ).fetchall()]
        scorecard = [dict(r) for r in conn.execute(
            "SELECT * FROM qa_scorecards WHERE call_id = ?", (call_id,)
        ).fetchall()]
        tickets = [dict(r) for r in conn.execute(
            "SELECT * FROM remediation_tickets WHERE call_id = ?", (call_id,)
        ).fetchall()]
        cache = conn.execute(
            "SELECT call_id, analyzed_at FROM analysis_cache WHERE call_id = ?", (call_id,)
        ).fetchone()
        return {
            "pci_findings": pci,
            "qa_scorecards": scorecard,
            "remediation_tickets": tickets,
            "cache_entry": dict(cache) if cache else None,
        }
    finally:
        conn.close()


# ============================================================
# ENTRY POINT — run at Docker build time
# ============================================================

if __name__ == "__main__":
    print(f"Initializing database at {DB_PATH}")
    conn = get_connection()
    create_schema(conn)
    seed_transcripts(conn)
    conn.close()
    print("Done. 5 transcripts seeded.")
    for t in TRANSCRIPTS:
        print(f"  {t['call_id']} | {t['agent_id']} | {t['queue_name']} | {t['duration_seconds']}s")
