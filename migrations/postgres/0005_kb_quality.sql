-- Licence / attribution of a source's content (e.g. "CC BY-SA 4.0, Odoo
-- S.A."), copied onto the entries drafted from it with the source URL.
-- SQLite twin: backend/db.py _ADDED_COLUMNS.
ALTER TABLE kb_sources ADD COLUMN licence_note TEXT;
ALTER TABLE kb_entries ADD COLUMN source_licence TEXT;
