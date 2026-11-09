"""Seed data, all idempotent so repeated `init_db()` calls (every app
startup) never duplicate or reset data a tester may have relied on.

- Default `departments` — skipped if any department exists, so an
  admin's edits survive restarts.
- One demo manager + one demo technician — dev only (APP_ENV !=
  production), skipped per email if it already exists.

The default categories are seeded by backend/categories.py.
"""

from __future__ import annotations

import json
import os
import uuid

import bcrypt


# Every default category (backend/categories.py) is owned by exactly one
# default department, so no category starts out unroutable.
DEFAULT_DEPARTMENTS = [
    ("Product Support", ["SETUP", "USAGE", "ISSUE", "INTEGRATION"]),
    ("Accounts & Billing", ["ACCOUNT", "BILLING", "DATA"]),
    ("General", ["OTHER"]),
]


def seed_departments(conn) -> None:
    if conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0]:
        return
    conn.executemany(
        "INSERT INTO departments (department_id, name, categories) VALUES (?, ?, ?)",
        [
            (f"DEPT-{uuid.uuid4().hex[:8]}", name, json.dumps(categories))
            for name, categories in DEFAULT_DEPARTMENTS
        ],
    )
    conn.commit()


# Dev-only accounts so every portal can be tried without the admin first
# creating staff. Never seeded when APP_ENV=production.
DEMO_STAFF = [
    {
        "name": "Demo Manager",
        "email": "manager@example.com",
        "password": "manager-demo-pass",
        "role": "manager",
        "department": "Product Support",
    },
    {
        "name": "Demo Technician",
        "email": "technician@example.com",
        "password": "technician-demo-pass",
        "role": "technician",
        "department": "Product Support",
    },
]


def seed_demo_staff(conn) -> None:
    if os.environ.get("APP_ENV", "development").lower() == "production":
        return
    for person in DEMO_STAFF:
        if conn.execute(
            "SELECT 1 FROM staff WHERE email = ?", (person["email"],)
        ).fetchone():
            continue
        prefix = "MGR" if person["role"] == "manager" else "TECH"
        staff_id = f"{prefix}-{uuid.uuid4().hex[:8]}"
        department = conn.execute(
            "SELECT department_id FROM departments WHERE name = ?", (person["department"],)
        ).fetchone() if person["department"] else None
        conn.execute(
            "INSERT INTO staff (staff_id, name, email, password_hash, role, department_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                staff_id,
                person["name"],
                person["email"],
                bcrypt.hashpw(person["password"].encode(), bcrypt.gensalt()).decode(),
                person["role"],
                department["department_id"] if department else None,
            ),
        )
    conn.commit()
