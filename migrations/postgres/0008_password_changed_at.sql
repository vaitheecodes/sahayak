-- A password change revokes the account's earlier tokens: Unix seconds of
-- the last change; auth._load_user refuses a token issued before it.
-- SQLite twin: backend/db.py SCHEMA / _ADDED_COLUMNS.
ALTER TABLE customers ADD COLUMN password_changed_at BIGINT;
ALTER TABLE staff ADD COLUMN password_changed_at BIGINT;
ALTER TABLE admins ADD COLUMN password_changed_at BIGINT;
