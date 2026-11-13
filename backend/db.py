"""Database connections + schema init for the ticket resolution app.

DB_BACKEND selects the database: `sqlite` (default: a local file, used
for local runs and the test suite) or `postgres` (backend/db_postgres.py:
pooled psycopg connections, versioned migrations in migrations/postgres).
Nothing outside this module should know how a connection is obtained;
both backends take the same SQLite-style SQL.

`DB_PATH` is overridable by env var because on Azure App Service only
/home persists across restarts and deploys — the rest of the container
filesystem is ephemeral, so the default path next to this module would
silently lose every ticket on a restart. In production set
DB_PATH=/home/data/ticketapp.db.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path

from backend import categories
from backend.seed_data import seed_demo_staff, seed_departments

_DEFAULT_DB_PATH = Path(__file__).resolve().parent / "ticketapp.db"
DB_PATH = Path(os.environ.get("DB_PATH") or _DEFAULT_DB_PATH)

# Ticket statuses (customer- and staff-facing, one vocabulary):
#   open              waiting on the support team (human queue, unassigned)
#   in_progress       a technician has picked it up
#   pending_customer  waiting on the customer (e.g. the AI asked a question)
#   resolved          answered, by the AI or a technician
#   closed            done; no further replies accepted
TICKET_STATUSES = ("open", "in_progress", "pending_customer", "resolved", "closed")

# The only ticket_messages a customer endpoint may ever return.
CUSTOMER_VISIBLE_SQL = (
    "(visibility = 'public_reply' OR (visibility = 'system_event' AND customer_visible = 1))"
)

# Pre-Stage-2 status names -> current ones (migrated in place on startup).
_LEGACY_STATUSES = {"awaiting_reply": "pending_customer", "assigned": "in_progress"}

# Staff = technicians and managers, one table with a role column. The
# single admin and customers stay in their own tables: customers own
# tickets (FK), and the admin is bootstrapped from env, never created
# through the API.
SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id          TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    email                TEXT NOT NULL UNIQUE,
    password_hash        TEXT NOT NULL,
    active               INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    password_changed_at  INTEGER
);

CREATE TABLE IF NOT EXISTS staff (
    staff_id             TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    email                TEXT NOT NULL UNIQUE,
    password_hash        TEXT NOT NULL,
    role                 TEXT NOT NULL DEFAULT 'technician',
    active               INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    -- Managers: the one department they manage; support engineers: the one they work.
    department_id        TEXT REFERENCES departments(department_id) ON DELETE SET NULL,
    -- Managers only (backend/permissions.py MANAGER_TYPES); NULL for anyone else.
    manager_type         TEXT,
    password_changed_at  INTEGER
);

CREATE TABLE IF NOT EXISTS admins (
    admin_id      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    password_changed_at INTEGER
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id              TEXT PRIMARY KEY,
    customer_id            TEXT NOT NULL REFERENCES customers(customer_id),
    channel                TEXT NOT NULL,
    ticket_text            TEXT NOT NULL,
    category               TEXT,
    confidence             REAL,
    route                  TEXT NOT NULL,
    ai_response            TEXT,
    status                 TEXT NOT NULL,
    assigned_technician_id TEXT REFERENCES staff(staff_id),
    clarification_attempts INTEGER NOT NULL DEFAULT 0,
    created_at             TIMESTAMP NOT NULL,
    ticket_type            TEXT NOT NULL DEFAULT 'chat',
    subject                TEXT,
    priority               TEXT NOT NULL DEFAULT 'medium',
    requested_category     TEXT,
    contact_name           TEXT,
    customer_last_read_at  TIMESTAMP,
    -- Set when the ticket was created by escalating a chat. The chat's
    -- transcript stays in chat_messages (not copied into the thread).
    chat_session_id        TEXT REFERENCES chat_sessions(session_id),
    -- Staff-only AI output (JSON): never returned by customer endpoints.
    ai_summary             TEXT,
    ai_suggestions         TEXT
);

-- sender: customer | ai | staff | system. author_id is the staff_id for
-- staff messages (null otherwise).
-- visibility: public_reply (the conversation), internal_note (staff only,
-- never returned by a customer endpoint), system_event (status/assignment
-- changes; shown to the customer only when customer_visible = 1).
-- Customer queries filter on these columns in SQL: CUSTOMER_VISIBLE_SQL.
CREATE TABLE IF NOT EXISTS ticket_messages (
    message_id       TEXT PRIMARY KEY,
    ticket_id        TEXT NOT NULL REFERENCES tickets(ticket_id),
    sender           TEXT NOT NULL,
    message          TEXT NOT NULL,
    created_at       TIMESTAMP NOT NULL,
    author_id        TEXT,
    visibility       TEXT NOT NULL DEFAULT 'public_reply',
    customer_visible INTEGER NOT NULL DEFAULT 1,
    subject          TEXT
);
CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket ON ticket_messages(ticket_id, created_at);

-- Every status / owner change, by whom ('system' for the AI pipeline).
CREATE TABLE IF NOT EXISTS ticket_status_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   TEXT NOT NULL REFERENCES tickets(ticket_id),
    from_status TEXT,
    to_status   TEXT NOT NULL,
    changed_by  TEXT NOT NULL,
    changed_at  TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status_history_ticket ON ticket_status_history(ticket_id);

CREATE TABLE IF NOT EXISTS ticket_assignment_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   TEXT NOT NULL REFERENCES tickets(ticket_id),
    from_user   TEXT,
    to_user     TEXT,
    changed_by  TEXT NOT NULL,
    changed_at  TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assignment_history_ticket ON ticket_assignment_history(ticket_id);

-- Customer-facing AI chat, a lifecycle separate from tickets:
--   active     the AI is handling it
--   resolved   the customer confirmed it's solved (summary + review record)
--   escalated  handed to the support team; escalated_ticket_id is the ticket
--   abandoned  ended without resolution or escalation
-- summary is the AI's JSON summary (resolution or escalation); internal only.
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id             TEXT PRIMARY KEY,
    customer_id            TEXT NOT NULL REFERENCES customers(customer_id),
    status                 TEXT NOT NULL DEFAULT 'active',
    issue                  TEXT NOT NULL,
    summary                TEXT,
    resolved_at            TIMESTAMP,
    created_at             TIMESTAMP NOT NULL,
    updated_at             TIMESTAMP NOT NULL,
    requested_category     TEXT,
    contact_name           TEXT,
    category               TEXT,
    confidence             REAL,
    last_route             TEXT,
    clarification_attempts INTEGER NOT NULL DEFAULT 0,
    escalated_ticket_id    TEXT,
    legacy_ticket_id       TEXT
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_customer ON chat_sessions(customer_id, created_at);

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id  TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES chat_sessions(session_id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, created_at);

-- "This reply was wrong" on a bot reply, saved with the customer's consent:
-- the chat as it was (customer-visible messages, JSON), replayed by the
-- chat eval (backend/evals/cases.feedback_cases). Postgres: 0009_chat_feedback.sql.
CREATE TABLE IF NOT EXISTS chat_feedback (
    feedback_id TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES chat_sessions(session_id),
    message_id  TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    consent     INTEGER NOT NULL,
    transcript  TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL
);

-- A customer question the KB didn't cover ("no guide", or a follow-up the
-- guide doesn't answer): the admin's Unanswered questions list (KB gaps).
-- Postgres: 0010_kb_unanswered.sql.
CREATE TABLE IF NOT EXISTS kb_unanswered (
    unanswered_id   TEXT PRIMARY KEY,
    question        TEXT NOT NULL,
    channel         TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    reason          TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL
);

-- Internal record for every AI-resolved chat, so staff can verify the
-- outcome and close it separately from the (already closed) customer chat.
CREATE TABLE IF NOT EXISTS chat_reviews (
    review_id   TEXT PRIMARY KEY,
    chat_id     TEXT NOT NULL UNIQUE REFERENCES chat_sessions(session_id),
    summary     TEXT,
    status      TEXT NOT NULL DEFAULT 'pending_review',
    reviewed_by TEXT,
    reviewed_at TIMESTAMP,
    created_at  TIMESTAMP NOT NULL
);

-- AI-detected incident clusters (backend/incidents.py). Tickets are only
-- ever *linked* to a cluster, never merged, closed or deleted by it.
--   detected             the AI found a plausible group; nobody has looked
--   under_investigation  a manager is looking into it
--   confirmed            a manager confirmed it (customers on linked
--                        tickets see a neutral "we're aware" banner)
--   dismissed            not an incident; its tickets aren't re-clustered
--   resolved             fixed, and the post-incident summary was sent
--                        (backend/incident_resolution.py)
-- summary: JSON of the AI judgement (facts, hypotheses, reasoning,
-- confidence reasons, next steps) + narrative. needs_routing = no
-- department was assigned (AI below the routing confidence bar).
CREATE TABLE IF NOT EXISTS incident_clusters (
    incident_id   TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'detected',
    category      TEXT,
    summary       TEXT NOT NULL,
    confidence    REAL NOT NULL,
    needs_routing INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP NOT NULL,
    updated_at    TIMESTAMP NOT NULL,
    -- Post-incident fields (UTC). started_at = first linked report;
    -- resolved_at = when staff say the fix was applied.
    started_at             TIMESTAMP,
    resolved_at            TIMESTAMP,
    resolution_note        TEXT,
    root_cause             TEXT,
    customer_summary       TEXT,
    internal_summary       TEXT,
    summary_status         TEXT NOT NULL DEFAULT 'none',          -- none|draft|approved|sent
    visibility             TEXT NOT NULL DEFAULT 'affected_only', -- affected_only|public
    assigned_technician_id TEXT REFERENCES staff(staff_id),
    resolved_by            TEXT
);

CREATE TABLE IF NOT EXISTS incident_tickets (
    incident_id TEXT NOT NULL REFERENCES incident_clusters(incident_id),
    ticket_id   TEXT NOT NULL REFERENCES tickets(ticket_id),
    added_at    TIMESTAMP NOT NULL,
    PRIMARY KEY (incident_id, ticket_id)
);
CREATE INDEX IF NOT EXISTS idx_incident_tickets_ticket ON incident_tickets(ticket_id);

-- source 'ai' (proposed by correlation) or 'manager' (set by a manager or
-- the admin, confirmed = 1). AI re-runs never touch manager rows.
CREATE TABLE IF NOT EXISTS incident_departments (
    incident_id   TEXT NOT NULL REFERENCES incident_clusters(incident_id),
    department_id TEXT NOT NULL REFERENCES departments(department_id) ON DELETE CASCADE,
    source        TEXT NOT NULL,
    confirmed     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (incident_id, department_id)
);

CREATE TABLE IF NOT EXISTS incident_reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL REFERENCES incident_clusters(incident_id),
    reviewer    TEXT NOT NULL,
    action      TEXT NOT NULL,
    note        TEXT,
    at          TIMESTAMP NOT NULL
);

-- One row per linked ticket per incident summary send: what makes "Approve
-- & send" idempotent (sent rows are never re-posted) and records failures
-- for retry.
CREATE TABLE IF NOT EXISTS incident_deliveries (
    incident_id  TEXT NOT NULL REFERENCES incident_clusters(incident_id),
    ticket_id    TEXT NOT NULL REFERENCES tickets(ticket_id),
    status       TEXT NOT NULL,              -- sent|failed
    message_id   TEXT,
    error        TEXT,
    attempted_at TIMESTAMP NOT NULL,
    PRIMARY KEY (incident_id, ticket_id)
);

-- What the help desk remembers about confirmed/resolved incidents, to
-- answer "did I have an issue?" (backend/incident_memory.py). Kept for
-- INCIDENT_MEMORY_DAYS after resolution. affected_customer_ids decides
-- who may hear about an affected_only incident; customer_summary is the
-- only text ever shown to customers.
CREATE TABLE IF NOT EXISTS incident_memory (
    incident_id           TEXT PRIMARY KEY REFERENCES incident_clusters(incident_id),
    status                TEXT NOT NULL,     -- confirmed|resolved
    category              TEXT,
    department_ids        TEXT NOT NULL DEFAULT '[]',
    started_at            TIMESTAMP,
    resolved_at           TIMESTAMP,
    customer_summary      TEXT,
    affected_customer_ids TEXT NOT NULL DEFAULT '[]',
    visibility            TEXT NOT NULL DEFAULT 'affected_only',
    embedding             TEXT,
    embedding_model       TEXT,
    updated_at            TIMESTAMP NOT NULL
);

-- Cached embedding per ticket text (only used when an embeddings
-- deployment is configured). text_hash invalidates it if the text changes.
CREATE TABLE IF NOT EXISTS ticket_embeddings (
    ticket_id TEXT PRIMARY KEY REFERENCES tickets(ticket_id),
    model     TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    vector    TEXT NOT NULL
);

-- Who did what, for the admin's audit log. detail is a small JSON object
-- (ids, statuses, names) — never message bodies, passwords or tokens.
CREATE TABLE IF NOT EXISTS audit_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id  TEXT NOT NULL,
    action    TEXT NOT NULL,
    entity    TEXT NOT NULL,
    entity_id TEXT,
    detail    TEXT NOT NULL DEFAULT '{}',
    at        TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_events_at ON audit_events(at);
CREATE INDEX IF NOT EXISTS idx_audit_events_entity ON audit_events(entity, entity_id);

-- Admin-editable application settings (backend/app_settings.py): one JSON
-- value per section. A missing row means "use the env/default value".
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_by TEXT,
    updated_at TIMESTAMP NOT NULL
);

-- Files live on disk under uploads_dir() with a server-generated
-- stored_name; `filename` is the customer's original name, display only.
CREATE TABLE IF NOT EXISTS attachments (
    attachment_id TEXT PRIMARY KEY,
    ticket_id     TEXT NOT NULL REFERENCES tickets(ticket_id),
    message_id    TEXT NOT NULL REFERENCES ticket_messages(message_id),
    filename      TEXT NOT NULL,
    stored_name   TEXT NOT NULL UNIQUE,
    content_type  TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    uploaded_by   TEXT NOT NULL,
    created_at    TIMESTAMP NOT NULL
);

-- categories: JSON array of category names (backend/categories.py). A
-- category belongs to at most one department (enforced in main.py) so
-- routing a ticket to "the department that owns its category" is never
-- ambiguous.
CREATE TABLE IF NOT EXISTS departments (
    department_id TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    categories    TEXT NOT NULL DEFAULT '[]'
);

-- Legacy (pre one-department-per-manager): read once by the migration
-- that sets staff.department_id, kept for history, no longer written.
CREATE TABLE IF NOT EXISTS manager_departments (
    manager_id    TEXT NOT NULL REFERENCES staff(staff_id) ON DELETE CASCADE,
    department_id TEXT NOT NULL REFERENCES departments(department_id) ON DELETE CASCADE,
    PRIMARY KEY (manager_id, department_id)
);

-- Knowledge base (backend/kb_store.py, backend/categories.py, kb_ingester/).
-- Categories are data: seeded with neutral defaults, the ingester may
-- propose more, only confirmed ones are used.
CREATE TABLE IF NOT EXISTS kb_categories (
    name         TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'confirmed',
    source       TEXT NOT NULL DEFAULT 'staff',
    created_at   TIMESTAMP NOT NULL,
    confirmed_by TEXT,
    confirmed_at TIMESTAMP
);

-- Where KB content comes from. public_confirmed_*: who confirmed the
-- content is public or allowed to be used, and when (required).
CREATE TABLE IF NOT EXISTS kb_sources (
    source_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                TEXT NOT NULL,
    name                TEXT NOT NULL,
    root_url            TEXT,
    config              TEXT NOT NULL DEFAULT '{}',
    public_confirmed_by TEXT NOT NULL,
    public_confirmed_at TIMESTAMP NOT NULL,
    active              INTEGER NOT NULL DEFAULT 1,
    created_by          TEXT NOT NULL,
    created_at          TIMESTAMP NOT NULL
);

-- One ingestion run of a source. Model calls are estimated before the run
-- starts and capped per run (model_call_cap) and per day; a run that hits
-- a cap stops with stop_reason set. errors: counts by reason code only.
CREATE TABLE IF NOT EXISTS kb_ingest_runs (
    run_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id             INTEGER NOT NULL REFERENCES kb_sources(source_id),
    status                TEXT NOT NULL,
    triggered_by          TEXT NOT NULL,
    created_at            TIMESTAMP NOT NULL,
    started_at            TIMESTAMP,
    finished_at           TIMESTAMP,
    estimated_model_calls INTEGER NOT NULL DEFAULT 0,
    model_call_cap        INTEGER NOT NULL,
    model_calls           INTEGER NOT NULL DEFAULT 0,
    stop_reason           TEXT,
    pages_fetched         INTEGER NOT NULL DEFAULT 0,
    pages_unchanged       INTEGER NOT NULL DEFAULT 0,
    pages_skipped         INTEGER NOT NULL DEFAULT 0,
    chunks                INTEGER NOT NULL DEFAULT 0,
    drafts_created        INTEGER NOT NULL DEFAULT 0,
    steps_rejected        INTEGER NOT NULL DEFAULT 0,
    errors                TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_kb_runs_source ON kb_ingest_runs(source_id, created_at);

-- A fetched page or file. Only its hash is kept, never the page itself.
CREATE TABLE IF NOT EXISTS kb_documents (
    document_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id     INTEGER NOT NULL REFERENCES kb_sources(source_id),
    location      TEXT NOT NULL,
    title         TEXT,
    content_hash  TEXT,
    http_status   INTEGER,
    etag          TEXT,
    last_modified TEXT,
    byte_size     INTEGER,
    state         TEXT NOT NULL,
    miss_count    INTEGER NOT NULL DEFAULT 0,
    fetched_at    TIMESTAMP,
    UNIQUE (source_id, location)
);

-- A heading section of a document. text is purged (purged_at) once every
-- draft from it is decided, or after the retention period.
CREATE TABLE IF NOT EXISTS kb_chunks (
    chunk_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id       INTEGER NOT NULL REFERENCES kb_documents(document_id) ON DELETE CASCADE,
    run_id            INTEGER REFERENCES kb_ingest_runs(run_id),
    ordinal           INTEGER NOT NULL,
    heading_path      TEXT NOT NULL DEFAULT '',
    text              TEXT,
    chunk_hash        TEXT NOT NULL,
    char_start        INTEGER,
    char_end          INTEGER,
    flagged_injection INTEGER NOT NULL DEFAULT 0,
    purged_at         TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_document ON kb_chunks(document_id);

CREATE TABLE IF NOT EXISTS kb_entries (
    kb_entry_id     TEXT PRIMARY KEY,
    status          TEXT NOT NULL,
    title           TEXT NOT NULL,
    answer          TEXT NOT NULL DEFAULT '',
    kind            TEXT,
    handling        TEXT NOT NULL DEFAULT 'answer',
    collect         TEXT NOT NULL DEFAULT '[]',
    category        TEXT NOT NULL,
    source_url      TEXT,
    document_id     INTEGER REFERENCES kb_documents(document_id) ON DELETE SET NULL,
    chunk_id        INTEGER REFERENCES kb_chunks(chunk_id) ON DELETE SET NULL,
    chunk_hash      TEXT,
    run_id          INTEGER REFERENCES kb_ingest_runs(run_id),
    stale           INTEGER NOT NULL DEFAULT 0,
    supersedes      TEXT,
    duplicate_of    TEXT,
    duplicate_score REAL,
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL,
    updated_by      TEXT,
    updated_at      TIMESTAMP NOT NULL,
    reviewed_by     TEXT,
    reviewed_at     TIMESTAMP,
    review_note     TEXT,
    version         INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_kb_entries_status ON kb_entries(status);

CREATE TABLE IF NOT EXISTS kb_entry_questions (
    entry_id TEXT NOT NULL REFERENCES kb_entries(kb_entry_id) ON DELETE CASCADE,
    ordinal  INTEGER NOT NULL,
    text     TEXT NOT NULL,
    PRIMARY KEY (entry_id, ordinal)
);

-- quote: the passage of the entry's chunk the step is backed by.
-- support_check: the second model check's verdict ("supported"), NULL
-- for steps written by staff.
CREATE TABLE IF NOT EXISTS kb_entry_steps (
    entry_id      TEXT NOT NULL REFERENCES kb_entries(kb_entry_id) ON DELETE CASCADE,
    ordinal       INTEGER NOT NULL,
    text          TEXT NOT NULL,
    quote         TEXT NOT NULL,
    quote_offset  INTEGER,
    support_check TEXT,
    PRIMARY KEY (entry_id, ordinal)
);

-- Product terms learned from the content: proposed by the ingester (or
-- staff), confirmed by a reviewer. pattern is built from label + aliases.
CREATE TABLE IF NOT EXISTS kb_terms (
    term_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    label             TEXT NOT NULL,
    kind              TEXT NOT NULL,
    aliases           TEXT NOT NULL DEFAULT '[]',
    pattern           TEXT NOT NULL,
    status            TEXT NOT NULL,
    merged_into       INTEGER REFERENCES kb_terms(term_id),
    evidence_quote    TEXT,
    evidence_chunk_id INTEGER REFERENCES kb_chunks(chunk_id) ON DELETE SET NULL,
    evidence_count    INTEGER NOT NULL DEFAULT 0,
    proposed_by       TEXT NOT NULL,
    created_at        TIMESTAMP NOT NULL,
    confirmed_by      TEXT,
    confirmed_at      TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_terms_label ON kb_terms(lower(label));

CREATE TABLE IF NOT EXISTS kb_entry_terms (
    entry_id TEXT NOT NULL REFERENCES kb_entries(kb_entry_id) ON DELETE CASCADE,
    term_id  INTEGER NOT NULL REFERENCES kb_terms(term_id) ON DELETE CASCADE,
    PRIMARY KEY (entry_id, term_id)
);
"""


# DELETE (the classic rollback journal) by default. WAL is faster for
# concurrent readers, but: it relies on shared memory that network file
# systems don't support reliably (on App Service the only persistent storage,
# /home, is a network share); and SQLite 3.51.0 (Anaconda's Python) deadlocked
# in WAL mode when several requests opened and closed connections at once
# (one thread in sqlite3WalClose, the rest in findReusableFd, all on the same
# mutex: every database endpoint hung). SQLITE_JOURNAL_MODE=WAL opts back in.
_JOURNAL_MODES = {"WAL", "DELETE", "TRUNCATE"}
DEFAULT_JOURNAL_MODE = "DELETE"


def _journal_mode() -> str:
    mode = (os.environ.get("SQLITE_JOURNAL_MODE") or "").strip().upper()
    return mode if mode in _JOURNAL_MODES else DEFAULT_JOURNAL_MODE


def backend_name() -> str:
    name = (os.environ.get("DB_BACKEND") or "sqlite").strip().lower()
    if name not in ("sqlite", "postgres"):
        raise ValueError("DB_BACKEND must be sqlite or postgres")
    return name


def is_postgres(conn=None) -> bool:
    if conn is not None:
        return getattr(conn, "backend", "sqlite") == "postgres"
    return backend_name() == "postgres"


def get_connection():
    if backend_name() == "postgres":
        from backend import db_postgres

        return db_postgres.get_connection()
    # timeout: wait for another request's write instead of failing at once.
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.execute(f"PRAGMA journal_mode={_journal_mode()}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def begin_write(conn, lock_key: str | None = None) -> None:
    """Start a write transaction that serialises with other writers.
    SQLite: BEGIN IMMEDIATE takes the database write lock now (not at the
    first write), so a check-then-write can't race another request.
    `lock_key` names what is being protected; backends with finer-grained
    locks use it (see db_postgres)."""
    if is_postgres(conn):
        from backend import db_postgres

        db_postgres.begin_write(conn, lock_key)
        return
    conn.execute("BEGIN IMMEDIATE")


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def _columns(conn, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_agents_to_staff(conn) -> None:
    """Pre-roles databases have an `agents` table and
    `tickets.assigned_agent_id`. Rename both in place: SQLite (>= 3.26,
    legacy_alter_table off) rewrites the FK in `tickets` to follow the
    renamed table/column, so existing assignments survive. Every legacy
    agent becomes a technician via the `role` column default."""
    if _table_exists(conn, "agents") and not _table_exists(conn, "staff"):
        conn.execute("ALTER TABLE agents RENAME TO staff")
        conn.execute("ALTER TABLE staff RENAME COLUMN agent_id TO staff_id")
    if _table_exists(conn, "staff"):
        cols = _columns(conn, "staff")
        if "role" not in cols:
            conn.execute("ALTER TABLE staff ADD COLUMN role TEXT NOT NULL DEFAULT 'technician'")
        if "active" not in cols:
            conn.execute("ALTER TABLE staff ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        if "must_change_password" not in cols:
            conn.execute(
                "ALTER TABLE staff ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
            )
    if _table_exists(conn, "tickets") and "assigned_agent_id" in _columns(conn, "tickets"):
        conn.execute(
            "ALTER TABLE tickets RENAME COLUMN assigned_agent_id TO assigned_technician_id"
        )


# Columns added after the first release. CREATE TABLE IF NOT EXISTS
# never alters an existing table, so older databases get them here.
_ADDED_COLUMNS = {
    "tickets": [
        ("ticket_type", "TEXT NOT NULL DEFAULT 'chat'"),
        ("subject", "TEXT"),
        ("priority", "TEXT NOT NULL DEFAULT 'medium'"),
        ("requested_category", "TEXT"),
        ("contact_name", "TEXT"),
        ("customer_last_read_at", "TIMESTAMP"),
        ("chat_session_id", "TEXT REFERENCES chat_sessions(session_id)"),
        ("ai_summary", "TEXT"),
        ("ai_suggestions", "TEXT"),
        # SLA and response times (backend/sla.py); Postgres: 0002_sla.sql.
        ("first_response_at", "TIMESTAMP"),
        ("resolved_at", "TIMESTAMP"),
        ("sla_first_response_minutes", "INTEGER"),
        ("sla_resolution_minutes", "INTEGER"),
        ("sla_first_response_due", "TIMESTAMP"),
        ("sla_resolution_due", "TIMESTAMP"),
        ("sla_paused_at", "TIMESTAMP"),
        ("sla_paused_seconds", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "customers": [
        ("active", "INTEGER NOT NULL DEFAULT 1"),
        ("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
        # Unix seconds; tokens issued before it are refused (auth._load_user).
        # Postgres: 0008_password_changed_at.sql.
        ("password_changed_at", "INTEGER"),
    ],
    "staff": [
        ("department_id", "TEXT REFERENCES departments(department_id) ON DELETE SET NULL"),
        # Postgres: 0006_manager_types.sql (with CHECKs on the values).
        ("manager_type", "TEXT"),
        ("password_changed_at", "INTEGER"),
    ],
    "admins": [("password_changed_at", "INTEGER")],
    "incident_clusters": [
        ("started_at", "TIMESTAMP"),
        ("resolved_at", "TIMESTAMP"),
        ("resolution_note", "TEXT"),
        ("root_cause", "TEXT"),
        ("customer_summary", "TEXT"),
        ("internal_summary", "TEXT"),
        ("summary_status", "TEXT NOT NULL DEFAULT 'none'"),
        ("visibility", "TEXT NOT NULL DEFAULT 'affected_only'"),
        ("assigned_technician_id", "TEXT REFERENCES staff(staff_id)"),
        ("resolved_by", "TEXT"),
    ],
    # KB ingester (kb_ingester/); Postgres: 0004_kb_ingest.sql, 0005_kb_quality.sql.
    "kb_ingest_runs": [("estimate", "TEXT NOT NULL DEFAULT '{}'")],
    "kb_documents": [("url", "TEXT"), ("pending_hash", "TEXT")],
    "kb_chunks": [("drafted_at", "TIMESTAMP")],
    "kb_entries": [("draft_notes", "TEXT NOT NULL DEFAULT '{}'"), ("source_licence", "TEXT"),
                   ("snippets", "TEXT NOT NULL DEFAULT '[]'")],
    "kb_categories": [("merged_into", "TEXT")],
    "kb_sources": [("licence_note", "TEXT")],
    "ticket_messages": [
        ("author_id", "TEXT"),
        ("visibility", "TEXT NOT NULL DEFAULT 'public_reply'"),
        ("customer_visible", "INTEGER NOT NULL DEFAULT 1"),
        ("subject", "TEXT"),
    ],
}


# Same backfill as migrations/postgres/0002_sla.sql; idempotent (only
# NULLs are filled).
_SLA_BACKFILL = """
-- First response: the first public reply by a staff member (an incident
-- broadcast has no author), or by the AI on a ticket it handled.
UPDATE tickets SET first_response_at = (
  SELECT MIN(m.created_at) FROM ticket_messages m
  WHERE m.ticket_id = tickets.ticket_id AND m.visibility = 'public_reply'
    AND ((m.sender = 'staff' AND m.author_id IS NOT NULL)
         OR (m.sender = 'ai' AND tickets.route <> 'human')))
WHERE first_response_at IS NULL;
-- Resolved: the latest move to Resolved/Closed of a ticket that is still so.
UPDATE tickets SET resolved_at = COALESCE((
  SELECT MAX(h.changed_at) FROM ticket_status_history h
  WHERE h.ticket_id = tickets.ticket_id AND h.to_status IN ('resolved', 'closed')), created_at)
WHERE resolved_at IS NULL AND status IN ('resolved', 'closed');
"""


def _add_missing_columns(conn) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        existing = _columns(conn, table)
        for name, ddl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    conn.executescript(_SLA_BACKFILL)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at)")
    for old, new in _LEGACY_STATUSES.items():
        conn.execute("UPDATE tickets SET status = ? WHERE status = ?", (new, old))
    # One department per manager: keep each manager's first legacy mapping.
    conn.execute(
        "UPDATE staff SET department_id = ("
        "  SELECT md.department_id FROM manager_departments md "
        "  WHERE md.manager_id = staff.staff_id ORDER BY md.rowid LIMIT 1) "
        "WHERE role = 'manager' AND department_id IS NULL"
    )
    # Manager types: a manager without one (from before them) is a Tech Lead;
    # anyone else has none.
    conn.execute("UPDATE staff SET manager_type = 'tech_lead' WHERE role = 'manager' AND manager_type IS NULL")
    conn.execute("UPDATE staff SET manager_type = NULL WHERE role != 'manager' AND manager_type IS NOT NULL")
    # Incidents from before post-incident fields: started_at = first report.
    conn.execute(
        "UPDATE incident_clusters SET started_at = ("
        "  SELECT MIN(t.created_at) FROM incident_tickets it JOIN tickets t "
        "  ON t.ticket_id = it.ticket_id WHERE it.incident_id = incident_clusters.incident_id) "
        "WHERE started_at IS NULL"
    )
    # Messages from before visibility types: system notes were always shown
    # to the customer, so they become customer-visible system events.
    conn.execute(
        "UPDATE ticket_messages SET visibility = 'system_event' "
        "WHERE sender = 'system' AND visibility = 'public_reply'"
    )


_LEGACY_ESCALATION_PREFIX = "This conversation has been escalated"
_LEGACY_REVIEW_SUMMARY = json.dumps(
    {"problem": None, "troubleshooting": [], "solution": None,
     "note": "Migrated from a pre-chat-session conversation; no AI summary was generated."}
)


def _migrate_chat_tickets(conn) -> None:
    """Before chat sessions existed, every chat was a `tickets` row with
    ticket_type='chat'. Move them to chat_sessions/chat_messages
    (idempotent: only rows with no chat_session_id are touched).

    - Escalated chats (route 'human') stay tickets. The pre-escalation
      conversation moves into the linked session's chat_messages; later
      thread messages (and the escalation note) stay in the ticket.
    - Every other chat was never a ticket in the new model: its messages
      move into a session ('resolved' if the customer closed it, else
      'active' so they can pick it up again) and the ticket row is
      removed. A resolved one gets a pending review record. Rows with
      attachments are left untouched rather than risk losing a file link.
    Data is moved, never dropped."""
    legacy = conn.execute(
        "SELECT * FROM tickets WHERE ticket_type = 'chat' AND chat_session_id IS NULL"
    ).fetchall()
    for ticket in legacy:
        ticket_id = ticket["ticket_id"]
        if conn.execute(
            "SELECT 1 FROM attachments WHERE ticket_id = ?", (ticket_id,)
        ).fetchone():
            continue
        messages = conn.execute(
            "SELECT * FROM ticket_messages WHERE ticket_id = ? ORDER BY created_at, rowid",
            (ticket_id,),
        ).fetchall()
        escalated = ticket["route"] == "human"
        if escalated:
            cut = next(
                (i for i, m in enumerate(messages)
                 if m["sender"] == "system" and m["message"].startswith(_LEGACY_ESCALATION_PREFIX)),
                len(messages),
            )
            moved = [m for m in messages[:cut] if m["sender"] in ("customer", "ai")]
            status = "escalated"
        else:
            moved = [m for m in messages if m["sender"] in ("customer", "ai")]
            status = "resolved" if ticket["status"] == "closed" else "active"

        session_id = f"CHAT-{uuid.uuid4().hex[:8]}"
        issue = ticket["subject"] or ticket["ticket_text"].split("\n", 1)[0][:200]
        last_at = moved[-1]["created_at"] if moved else ticket["created_at"]
        conn.execute(
            "INSERT INTO chat_sessions (session_id, customer_id, status, issue, resolved_at, "
            "created_at, updated_at, requested_category, contact_name, category, confidence, "
            "last_route, clarification_attempts, escalated_ticket_id, legacy_ticket_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, ticket["customer_id"], status, issue,
                last_at if status == "resolved" else None,
                ticket["created_at"], last_at, ticket["requested_category"],
                ticket["contact_name"], ticket["category"], ticket["confidence"],
                None if escalated else ticket["route"], ticket["clarification_attempts"],
                ticket_id if escalated else None, ticket_id,
            ),
        )
        conn.executemany(
            "INSERT INTO chat_messages (message_id, session_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [(m["message_id"], session_id, m["sender"], m["message"], m["created_at"]) for m in moved],
        )
        if status == "resolved":
            conn.execute(
                "INSERT INTO chat_reviews (review_id, chat_id, summary, status, created_at) "
                "VALUES (?, ?, ?, 'pending_review', ?)",
                (f"REV-{uuid.uuid4().hex[:8]}", session_id, _LEGACY_REVIEW_SUMMARY, last_at),
            )
        if escalated:
            conn.executemany(
                "DELETE FROM ticket_messages WHERE message_id = ?",
                [(m["message_id"],) for m in moved],
            )
            conn.execute(
                "UPDATE tickets SET chat_session_id = ? WHERE ticket_id = ?", (session_id, ticket_id)
            )
        else:
            conn.execute("DELETE FROM ticket_messages WHERE ticket_id = ?", (ticket_id,))
            conn.execute("DELETE FROM tickets WHERE ticket_id = ?", (ticket_id,))


def uploads_dir() -> Path:
    """Attachment storage, next to the database so it follows DB_PATH: on
    App Service DB_PATH=/home/data/ticketapp.db puts uploads under
    /home/data/uploads, which persists across restarts."""
    path = Path(DB_PATH).parent / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _init_postgres() -> None:
    """Versioned migrations, then the same seeds as SQLite."""
    from backend import db_postgres

    db_postgres.wait_until_ready()
    db_postgres.migrate()
    conn = get_connection()
    try:
        categories.seed(conn)
        seed_departments(conn)
        seed_demo_staff(conn)
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    if backend_name() == "postgres":
        _init_postgres()
        return
    # Reads the module attribute rather than the import-time constant so a
    # test (or a script) that repoints DB_PATH still gets its directory
    # created. /home/data on App Service does not exist until something
    # makes it.
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        # Migrate before SCHEMA, or CREATE TABLE IF NOT EXISTS would make
        # an empty `staff` next to the legacy `agents` table.
        _migrate_agents_to_staff(conn)
        conn.executescript(SCHEMA)
        _add_missing_columns(conn)
        conn.commit()
        with conn:
            _migrate_chat_tickets(conn)
        categories.seed(conn)
        seed_departments(conn)
        seed_demo_staff(conn)
    finally:
        conn.close()
