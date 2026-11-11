-- KB entry snippets: up to three code, config or command lines copied
-- verbatim from the source chunk (kb_ingester/checks.snippet_problem),
-- shown to the customer as plain text in a code block, never executed.
-- A JSON list of strings, like `collect`.
-- SQLite twin: backend/db.py _ADDED_COLUMNS.
ALTER TABLE kb_entries ADD COLUMN snippets TEXT NOT NULL DEFAULT '[]';
