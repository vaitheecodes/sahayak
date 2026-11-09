"""Local SQLite uses the classic DELETE journal by default (backend/db.py):
WAL deadlocked under concurrent requests with SQLite 3.51.0 and isn't
reliable on network file systems. SQLITE_JOURNAL_MODE=WAL opts back in."""

from __future__ import annotations

import pytest

from backend import db

pytestmark = pytest.mark.sqlite_only


@pytest.mark.parametrize("value, expected", [
    (None, "DELETE"), ("", "DELETE"), ("  ", "DELETE"), ("delete", "DELETE"),
    ("WAL", "WAL"), (" wal ", "WAL"), ("truncate", "TRUNCATE"), ("memory", "DELETE"),
])
def test_journal_mode_setting(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("SQLITE_JOURNAL_MODE", raising=False)
    else:
        monkeypatch.setenv("SQLITE_JOURNAL_MODE", value)
    assert db._journal_mode() == expected


@pytest.mark.parametrize("setting, mode", [(None, "delete"), ("WAL", "wal")])
def test_connections_use_the_journal_mode(tmp_path, monkeypatch, setting, mode):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "journal.db")
    if setting is None:
        monkeypatch.delenv("SQLITE_JOURNAL_MODE", raising=False)
    else:
        monkeypatch.setenv("SQLITE_JOURNAL_MODE", setting)
    conn = db.get_connection()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == mode
    finally:
        conn.close()


def test_an_existing_wal_database_switches_back_on_its_next_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "was-wal.db")
    monkeypatch.setenv("SQLITE_JOURNAL_MODE", "WAL")
    db.get_connection().close()
    monkeypatch.delenv("SQLITE_JOURNAL_MODE")
    conn = db.get_connection()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        conn.close()
