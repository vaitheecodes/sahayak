-- Manager types (backend/permissions.py): Tech Lead, Product Manager and
-- Incident Manager are peers with the department scope; a Platform Lead
-- sees every department. Only managers have a type; the managers there
-- already are become Tech Leads. Read from the database on every request,
-- never from the token.
-- SQLite twin: backend/db.py SCHEMA / _ADDED_COLUMNS and its backfill.
ALTER TABLE staff ADD COLUMN manager_type TEXT
    CHECK (manager_type IN ('tech_lead', 'product_manager', 'incident_manager', 'platform_lead'));
UPDATE staff SET manager_type = 'tech_lead' WHERE role = 'manager';
ALTER TABLE staff ADD CONSTRAINT staff_manager_type_managers_only
    CHECK ((role = 'manager') = (manager_type IS NOT NULL));
