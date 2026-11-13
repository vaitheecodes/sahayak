-- A customer question the KB didn't cover ("no guide", or a follow-up the
-- guide doesn't answer): the admin's Unanswered questions list (KB gaps).
-- SQLite twin: backend/db.py SCHEMA.
CREATE TABLE kb_unanswered (
    unanswered_id   TEXT PRIMARY KEY,
    question        TEXT NOT NULL,
    channel         TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    reason          TEXT NOT NULL CHECK (reason IN ('no_guide', 'followup_not_covered')),
    created_at      TIMESTAMPTZ NOT NULL
);
