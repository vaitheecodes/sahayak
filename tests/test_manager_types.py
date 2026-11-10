"""Manager types (backend/permissions.py): Tech Lead, Product Manager and
Incident Manager are peers with today's department scope; a Platform Lead
sees every department.

- Data: staff.manager_type, only for managers (Tech Lead by default and
  for managers from before types); a role change sets or clears it; only
  the admin sets it, never on the admin account; changes are audited with
  the old and new type. The demo Platform Lead is a dev seed only.
- The type is read from the database on every request, never the token.

Runs on SQLite and, with DB_BACKEND=postgres, on Postgres (tests/conftest.py).
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from backend import db, main, permissions, runtime, seed_data

_counter = itertools.count()


class _Human:
    def invoke(self, state):
        return {"route": "human", "category": "ISSUE", "confidence": 0.5, "clarification_attempts": 0}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    with TestClient(main.app) as c:
        runtime.set_graph(_Human())
        yield c


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _login(client, email, password):
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return _bearer(res.json()["token"])


def _admin(client):
    return _login(client, "admin@example.com", "admin-dev-password")


def _sql(sql, params=()):
    conn = db.get_connection()
    try:
        cur = conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        conn.commit()
        return rows
    finally:
        conn.close()


def _type(staff_id):
    return _sql("SELECT manager_type FROM staff WHERE staff_id = ?", (staff_id,))[0]["manager_type"]


def _create(client, role, **extra):
    res = client.post("/api/admin/users", json={
        "name": f"{role} {next(_counter)}", "email": f"mt-{next(_counter)}@example.com", "role": role, **extra},
        headers=_admin(client))
    return res


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
def test_the_permission_table_has_every_type_and_the_peers_match():
    assert set(permissions.PERMISSIONS) == set(permissions.MANAGER_TYPES) == set(permissions.LABELS)
    peers = [permissions.PERMISSIONS[t] for t in ("tech_lead", "product_manager", "incident_manager")]
    assert peers[0] == peers[1] == peers[2]
    assert all(v == permissions.DEPARTMENT for k, v in peers[0].items() if k != "teams")
    assert permissions.sees_all({"role": "manager", "manager_type": "platform_lead"})
    # A manager from before types, and anyone who isn't a manager.
    assert permissions.manager_type({"role": "manager", "manager_type": None}) == "tech_lead"
    for user in ({"role": "admin", "manager_type": "platform_lead"}, {"role": "technician"}):
        assert permissions.manager_type(user) is None and not permissions.sees_all(user)


def test_existing_managers_become_tech_leads(client):
    rows = _sql("SELECT email, manager_type FROM staff WHERE role = 'manager'")
    assert {r["email"]: r["manager_type"] for r in rows}["manager@example.com"] == "tech_lead"
    assert not _sql("SELECT 1 FROM staff WHERE role != 'manager' AND manager_type IS NOT NULL")
    if db.is_postgres():
        # 0006_manager_types.sql: the values and "managers only" are constraints.
        with pytest.raises(Exception):
            _sql("UPDATE staff SET manager_type = 'boss' WHERE email = 'manager@example.com'")
        with pytest.raises(Exception):
            _sql("UPDATE staff SET manager_type = 'tech_lead' WHERE role = 'technician'")
    else:
        # A database from before types: the startup backfill makes them Tech Leads.
        _sql("UPDATE staff SET manager_type = NULL WHERE role = 'manager'")
        db.init_db()
        assert _sql("SELECT manager_type FROM staff WHERE email = 'manager@example.com'") == [
            {"manager_type": "tech_lead"}]


def test_admin_sets_the_type_and_a_role_change_sets_or_clears_it(client):
    admin = _admin(client)
    plain = _create(client, "manager").json()
    assert plain["manager_type"] == "tech_lead"
    lead = _create(client, "manager", manager_type="platform_lead").json()
    assert lead["manager_type"] == "platform_lead" == _type(lead["user_id"])
    assert _create(client, "technician", manager_type="platform_lead").status_code == 400
    assert _create(client, "customer", manager_type="tech_lead").status_code == 400
    assert _create(client, "manager", manager_type="boss").status_code == 422

    res = client.patch(f"/api/admin/users/{plain['user_id']}", json={"manager_type": "incident_manager"}, headers=admin)
    assert res.status_code == 200 and res.json()["manager_type"] == "incident_manager"
    res = client.patch(f"/api/admin/users/{plain['user_id']}", json={"name": "Renamed"}, headers=admin)
    assert res.json()["manager_type"] == "incident_manager"  # kept when not sent
    # To support engineer: no type; back to manager: a Tech Lead again.
    res = client.patch(f"/api/admin/users/{plain['user_id']}", json={"role": "technician"}, headers=admin)
    assert res.json()["manager_type"] is None and _type(plain["user_id"]) is None
    assert client.patch(f"/api/admin/users/{plain['user_id']}", json={"manager_type": "tech_lead"},
                        headers=admin).status_code == 400
    res = client.patch(f"/api/admin/users/{plain['user_id']}", json={"role": "manager"}, headers=admin)
    assert res.json()["manager_type"] == "tech_lead"
    res = client.patch(f"/api/admin/users/{plain['user_id']}",
                       json={"role": "technician", "manager_type": "platform_lead"}, headers=admin)
    assert res.status_code == 400 and _type(plain["user_id"]) == "tech_lead"
    listed = {u["user_id"]: u for u in client.get("/api/admin/users", headers=admin).json()}
    assert listed[lead["user_id"]]["manager_type"] == "platform_lead"


def test_the_admin_account_never_gets_a_manager_type(client):
    admin = _admin(client)
    admin_id = client.get("/api/auth/me", headers=admin).json()["user_id"]
    res = client.patch(f"/api/admin/users/{admin_id}", json={"manager_type": "platform_lead"}, headers=admin)
    assert res.status_code == 403
    res = client.patch(f"/api/admin/staff/{admin_id}", json={"manager_type": "platform_lead"}, headers=admin)
    assert res.status_code == 404
    assert not _sql("SELECT 1 FROM staff WHERE staff_id = ?", (admin_id,))


def test_type_changes_are_audited_with_the_old_and_new_type(client):
    admin = _admin(client)
    user = _create(client, "manager").json()
    client.patch(f"/api/admin/users/{user['user_id']}", json={"manager_type": "platform_lead"}, headers=admin)
    client.patch(f"/api/admin/users/{user['user_id']}", json={"manager_type": "platform_lead"}, headers=admin)
    events = client.get("/api/admin/audit", params={"entity_id": user["user_id"]}, headers=admin).json()["events"]
    assert [e["action"] for e in events] == ["staff.updated", "staff.created"]  # the no-op isn't logged
    assert events[0]["detail"]["manager_type"] == "platform_lead"
    assert events[0]["detail"]["previous_manager_type"] == "tech_lead"
    assert events[1]["detail"]["manager_type"] == "tech_lead"


def test_the_demo_platform_lead_is_a_dev_seed_only(client, monkeypatch):
    lead = seed_data.DEMO_PLATFORM_LEAD
    assert lead["name"].startswith("Demo ")
    (row,) = _sql("SELECT role, manager_type, department_id FROM staff WHERE email = ?", (lead["email"],))
    assert row == {"role": "manager", "manager_type": "platform_lead", "department_id": None}
    _login(client, lead["email"], lead["password"])

    _sql("DELETE FROM staff WHERE email = ?", (lead["email"],))
    monkeypatch.setenv("APP_ENV", "production")
    conn = db.get_connection()
    try:
        seed_data.seed_demo_staff(conn)
    finally:
        conn.close()
    assert not _sql("SELECT 1 FROM staff WHERE email = ?", (lead["email"],))
