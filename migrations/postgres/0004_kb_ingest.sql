-- KB ingester runs (kb_ingester/runs.py; SQLite twin: backend/db.py
-- _ADDED_COLUMNS).
-- A run's estimate (pages, chunks, model calls) as shown before it starts.
ALTER TABLE kb_ingest_runs ADD COLUMN estimate TEXT NOT NULL DEFAULT '{}';
-- url: where the document was read from (after redirects). pending_hash:
-- the hash of the version being drafted; it becomes content_hash once
-- every chunk of it is drafted, so a run stopped at its cap is resumed.
ALTER TABLE kb_documents ADD COLUMN url TEXT;
ALTER TABLE kb_documents ADD COLUMN pending_hash TEXT;
-- When the chunk was drafted (NULL: still to do).
ALTER TABLE kb_chunks ADD COLUMN drafted_at TIMESTAMPTZ;
-- What the drafting checks did to an entry (removed answer, output
-- signals, proposed category): codes only.
ALTER TABLE kb_entries ADD COLUMN draft_notes TEXT NOT NULL DEFAULT '{}';
ALTER TABLE kb_categories ADD COLUMN merged_into TEXT;
