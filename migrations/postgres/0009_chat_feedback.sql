-- "This reply was wrong" on a bot reply, saved with the customer's consent:
-- the chat as it was (customer-visible messages, JSON), replayed by the
-- chat eval as a permanent regression case.
-- SQLite twin: backend/db.py SCHEMA.
CREATE TABLE chat_feedback (
    feedback_id TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES chat_sessions(session_id),
    message_id  TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    consent     INTEGER NOT NULL,
    transcript  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);
