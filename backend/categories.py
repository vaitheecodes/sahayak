"""Ticket and KB categories: data in the `kb_categories` table, not code.

Sahayak supports a product it doesn't know in advance, so the categories
the classifier picks from, departments own and the KB labels its entries
with are rows. A new database starts with DEFAULT_CATEGORIES (neutral
support topics, `source = 'seed'`); the KB ingester may propose more
(`status = 'proposed'`), and only confirmed ones are used anywhere.

Cached per process like app_settings: loaded at startup (load()) and
refreshed by every change made through this module. With nothing loaded
(the pure-function tests) the defaults apply; use() replaces the list
for a test.
"""

from __future__ import annotations

import re

from backend.timeutil import utcnow

# (name, label, description). ACCOUNT, BILLING and DATA are the default
# high-risk categories (app_settings.RoutingSettings).
DEFAULT_CATEGORIES = (
    ("ACCOUNT", "Account & sign-in", "Signing in, users, roles and permissions"),
    ("BILLING", "Billing & plans", "Plans, invoices, payments and licences"),
    ("DATA", "Data & privacy", "Importing, exporting, keeping or deleting data"),
    ("SETUP", "Setup", "Getting started, installing and configuring"),
    ("USAGE", "Using the product", "How to do a task"),
    ("ISSUE", "Something isn't working", "Errors and unexpected behaviour"),
    ("INTEGRATION", "Integrations", "Connecting other tools"),
    ("OTHER", "Other", "Anything else"),
)
NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,40}$")
STATUSES = ("proposed", "confirmed", "rejected", "merged")

_cache: list[dict] | None = None


def _defaults() -> list[dict]:
    return [{"name": n, "label": label, "description": d} for n, label, d in DEFAULT_CATEGORIES]


def _rows() -> list[dict]:
    return _cache if _cache is not None else _defaults()


def names() -> list[str]:
    """The confirmed categories, alphabetical."""
    return [row["name"] for row in _rows()]


def labels() -> dict[str, str]:
    return {row["name"]: row["label"] for row in _rows()}


def described() -> list[dict]:
    """name, label and description of every confirmed category."""
    return [dict(row) for row in _rows()]


def load(conn) -> None:
    global _cache
    _cache = [dict(row) for row in conn.execute(
        "SELECT name, label, description FROM kb_categories WHERE status = 'confirmed' ORDER BY name")]
    if not _cache:  # a database seeded before this table existed
        _cache = None


def use(rows: list[dict] | None) -> None:
    """Replace the categories (tests); None goes back to the defaults."""
    global _cache
    _cache = [dict(row) for row in rows] if rows is not None else None


def clear_cache() -> None:
    use(None)


def seed(conn) -> None:
    """DEFAULT_CATEGORIES, once, into an empty table."""
    if conn.execute("SELECT COUNT(*) FROM kb_categories").fetchone()[0]:
        return
    conn.executemany(
        "INSERT INTO kb_categories (name, label, description, status, source, created_at) "
        "VALUES (?, ?, ?, 'confirmed', 'seed', ?)",
        [(n, label, d, utcnow().isoformat()) for n, label, d in DEFAULT_CATEGORIES],
    )
    conn.commit()


def problem(name) -> str | None:
    """Why `name` can't be a category name (None: it can)."""
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        return "must be 2-41 capital letters, digits or underscores, starting with a letter"
    return None


def add(conn, name: str, label: str, description: str = "", *, status: str = "confirmed",
        source: str = "staff") -> None:
    """A new category (an existing name is left as it is). The caller
    commits; the cache is reloaded from `conn`."""
    if problem(name):
        raise ValueError(f"Category {name!r} {problem(name)}")
    if status not in STATUSES:
        raise ValueError(f"Unknown category status {status!r}")
    if conn.execute("SELECT 1 FROM kb_categories WHERE name = ?", (name,)).fetchone():
        return
    conn.execute(
        "INSERT INTO kb_categories (name, label, description, status, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, label.strip() or name, description.strip(), status, source, utcnow().isoformat()),
    )
    load(conn)


def all_rows(conn) -> list[dict]:
    """Every category with its status (the reviewer's list)."""
    return [dict(row) for row in conn.execute(
        "SELECT name, label, description, status, source, created_at, confirmed_by, confirmed_at, merged_into "
        "FROM kb_categories ORDER BY CASE status WHEN 'proposed' THEN 0 WHEN 'confirmed' THEN 1 ELSE 2 END, name")]


def decide(conn, name: str, status: str, actor: str, *, merged_into: str | None = None) -> None:
    """A proposed category confirmed, rejected or merged into a confirmed
    one. The caller commits; the cache is reloaded from `conn`."""
    if status not in ("confirmed", "rejected", "merged"):
        raise ValueError(f"Unknown decision {status!r}")
    row = conn.execute("SELECT status FROM kb_categories WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise LookupError(name)
    if row["status"] != "proposed":
        raise ValueError("Only a proposed category can be decided")
    if status == "merged":
        target = conn.execute("SELECT status FROM kb_categories WHERE name = ?", (merged_into,)).fetchone()
        if target is None or target["status"] != "confirmed":
            raise ValueError("A category can only be merged into a confirmed one")
    conn.execute(
        "UPDATE kb_categories SET status = ?, confirmed_by = ?, confirmed_at = ?, merged_into = ? WHERE name = ?",
        (status, actor, utcnow().isoformat(), merged_into if status == "merged" else None, name))
    load(conn)
