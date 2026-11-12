"""Manager types (backend/permissions.py): Tech Lead, Product Manager and
Incident Manager are peers with today's department scope; a Platform Lead
sees every department.

- Data: staff.manager_type, only for managers (Tech Lead by default and
  for managers from before types); a role change sets or clears it; only
  the admin sets it, never on the admin account; changes are audited with
  the old and new type. The demo Platform Lead is a dev seed only.
- The type is read from the database on every request, never the token.
- Scope: the three peer types keep the department scope (lists, opening a
  ticket by id, reassign inside the department, no department picker, no
  Teams); a Platform Lead sees every department or one it picks, opens any
  ticket and incident, hands a ticket to any support engineer (the ticket
  stays with its department; audited) and sees Teams. A demoted Platform
  Lead's token loses all of that on the next request, demoting the last one
  breaks nothing, and the admin gets 403 everywhere here.

Runs on SQLite and, with DB_BACKEND=postgres, on Postgres (tests/conftest.py).
"""

from __future__ import annotations

import itertools
import json

import pytest
from fastapi.testclient import TestClient

from backend import db, main, permissions, runtime, seed_data, sla

_counter = itertools.count()


class _Human:
    category = "ISSUE"

    def invoke(self, state):
        return {"route": "human", "category": self.category, "confidence": 0.5, "clarification_attempts": 0}


_graph = _Human()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    with TestClient(main.app) as c:
        runtime.set_graph(_graph)
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


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------
def _department_id(client, name):
    departments = client.get("/api/admin/departments", headers=_admin(client)).json()["departments"]
    return next(d["department_id"] for d in departments if d["name"] == name)


def _signed_in(client, role, department=None, **extra):
    """A new staff member (past the forced password change) and their id."""
    body = {"department_id": _department_id(client, department)} if department else {}
    res = _create(client, role, **body, **extra)
    assert res.status_code == 200, res.text
    user = res.json()
    headers = _login(client, user["email"], user["temporary_password"])
    # The change revokes the temporary-password token.
    headers = {"Authorization": "Bearer " + client.post("/api/auth/change-password", json={"current_password": user["temporary_password"],
                                                   "new_password": "real-pass-456"}, headers=headers).json()["token"]}
    return headers, user["user_id"]


def _raise(client, category):
    customer = client.post("/api/auth/customer/signup", json={
        "name": "Dana", "email": f"mt-cust-{next(_counter)}@example.com", "password": "password123"}).json()
    _graph.category = category
    res = client.post("/api/tickets", json={"subject": f"{category} problem", "description": "It is broken.",
                                            "priority": "medium"},
                      headers=_bearer(customer["token"]))
    assert res.status_code == 200, res.text
    return res.json()["ticket_id"]


def _ids(client, headers, **params):
    res = client.get("/api/manager/tickets", params=params, headers=headers)
    assert res.status_code == 200, res.text
    return {t["ticket_id"] for t in res.json()["tickets"]}


def _incident(other_department_id, ticket_id):
    """A confirmed incident linked to one department only."""
    incident_id = f"INC-mt{next(_counter)}"
    now = sla.iso(sla.now())
    _sql("INSERT INTO incident_clusters (incident_id, title, status, summary, confidence, created_at, updated_at) "
         "VALUES (?, 'Billing outage', 'confirmed', ?, 0.9, ?, ?)",
         (incident_id, json.dumps({"summary": "Invoices fail."}), now, now))
    _sql("INSERT INTO incident_departments (incident_id, department_id, source, confirmed) VALUES (?, ?, 'ai', 1)",
         (incident_id, other_department_id))
    _sql("INSERT INTO incident_tickets (incident_id, ticket_id, added_at) VALUES (?, ?, ?)", (incident_id, ticket_id, now))
    return incident_id


@pytest.mark.parametrize("kind", ["tech_lead", "product_manager", "incident_manager"])
def test_peer_types_keep_the_department_scope(client, kind):
    manager, _ = _signed_in(client, "manager", "Product Support", manager_type=kind)
    _, insider = _signed_in(client, "technician", "Product Support")
    _, outsider = _signed_in(client, "technician", "Accounts & Billing")
    mine, theirs = _raise(client, "ISSUE"), _raise(client, "BILLING")
    incident = _incident(_department_id(client, "Accounts & Billing"), theirs)

    assert _ids(client, manager) == {mine}
    assert client.get(f"/api/staff/tickets/{theirs}", headers=manager).status_code == 403
    assert client.post(f"/api/manager/tickets/{theirs}/reassign", json={"technician_id": insider},
                       headers=manager).status_code == 403
    assert client.post(f"/api/manager/tickets/{mine}/reassign", json={"technician_id": outsider},
                       headers=manager).status_code == 400
    assert client.post(f"/api/manager/tickets/{mine}/reassign", json={"technician_id": insider},
                       headers=manager).status_code == 200
    for path in ("/api/manager/tickets", "/api/manager/dashboard", "/api/manager/sla", "/api/manager/technicians"):
        assert client.get(path, params={"department": "all"}, headers=manager).status_code == 403, path
    assert client.get("/api/manager/teams", headers=manager).status_code == 403
    assert [d["name"] for d in client.get("/api/manager/departments", headers=manager).json()] == ["Product Support"]
    assert client.get(f"/api/incidents/{incident}", headers=manager).status_code == 403
    me = client.get("/api/auth/me", headers=manager).json()
    assert me["manager_type"] == kind and me["permissions"]["tickets"] == "department"


def test_platform_lead_sees_every_department_or_the_one_it_picks(client):
    lead, _ = _signed_in(client, "manager", manager_type="platform_lead")
    issue, billing = _raise(client, "ISSUE"), _raise(client, "BILLING")
    billing_id = _department_id(client, "Accounts & Billing")

    assert {issue, billing} <= _ids(client, lead)
    assert {issue, billing} <= _ids(client, lead, department="all")
    assert _ids(client, lead, department=billing_id) == {billing}
    assert client.get("/api/manager/tickets", params={"department": "DEPT-nope"}, headers=lead).status_code == 404
    dashboard = client.get("/api/manager/dashboard", params={"period": "this_year"}, headers=lead).json()
    assert dashboard["all_departments"] is True and dashboard["by_status"]["total"] >= 2
    picked = client.get("/api/manager/dashboard", params={"period": "this_year", "department": billing_id},
                        headers=lead).json()
    assert picked["department"]["department_id"] == billing_id and picked["by_status"]["total"] == 1
    assert client.get("/api/manager/sla", params={"department": billing_id}, headers=lead).status_code == 200
    assert client.get(f"/api/staff/tickets/{billing}", headers=lead).status_code == 200
    names = {d["name"] for d in client.get("/api/manager/departments", headers=lead).json()}
    assert {"Product Support", "Accounts & Billing", "General"} <= names
    incident = _incident(billing_id, billing)
    detail = client.get(f"/api/incidents/{incident}", headers=lead).json()
    assert detail["tickets"][0]["can_open"] is True
    assert incident in {i["incident_id"] for i in client.get("/api/incidents", headers=lead).json()}
    me = client.get("/api/auth/me", headers=lead).json()
    assert me["manager_type"] == "platform_lead" and me["permissions"]["teams"] is True


def test_platform_lead_reassigns_across_departments_without_moving_the_ticket(client):
    lead, lead_id = _signed_in(client, "manager", manager_type="platform_lead")
    manager, _ = _signed_in(client, "manager", "Product Support")
    _, billing_engineer = _signed_in(client, "technician", "Accounts & Billing")
    _, nobody_engineer = _signed_in(client, "technician")
    ticket = _raise(client, "ISSUE")
    engineers = {t["staff_id"] for t in client.get("/api/manager/technicians", headers=lead).json()["technicians"]}
    assert {billing_engineer, nobody_engineer} <= engineers

    res = client.post(f"/api/manager/tickets/{ticket}/reassign", json={"technician_id": billing_engineer},
                      headers=lead)
    assert res.status_code == 200, res.text
    assert ticket in _ids(client, manager)  # still Product Support's ticket
    (event,) = [e for e in client.get("/api/admin/audit", params={"entity_id": ticket}, headers=_admin(client))
                .json()["events"] if e["action"] == "ticket.reassigned_across_departments"]
    assert event["actor_id"] == lead_id
    assert event["detail"] == {"from_user": None, "to_user": billing_engineer,
                               "from_department_id": _department_id(client, "Product Support"),
                               "to_department_id": _department_id(client, "Accounts & Billing")}
    assert client.post(f"/api/manager/tickets/{ticket}/reassign", json={"technician_id": nobody_engineer},
                       headers=lead).status_code == 200


def test_platform_lead_sees_every_team(client):
    lead, _ = _signed_in(client, "manager", manager_type="platform_lead")
    _, engineer = _signed_in(client, "technician", "Accounts & Billing")
    teams = client.get("/api/manager/teams", headers=lead).json()
    (billing,) = [d for d in teams["departments"] if d["name"] == "Accounts & Billing"]
    assert engineer in {e["staff_id"] for e in billing["engineers"]}
    (support,) = [d for d in teams["departments"] if d["name"] == "Product Support"]
    assert [(m["email"], m["manager_type"]) for m in support["managers"]] == [("manager@example.com", "tech_lead")]
    assert seed_data.DEMO_PLATFORM_LEAD["email"] in {m["email"] for m in teams["no_department"]["managers"]}


def test_a_stale_token_loses_platform_lead_access_at_once(client):
    lead, lead_id = _signed_in(client, "manager", "Product Support", manager_type="platform_lead")
    billing = _raise(client, "BILLING")
    assert client.get(f"/api/staff/tickets/{billing}", headers=lead).status_code == 200

    client.patch(f"/api/admin/users/{lead_id}", json={"manager_type": "tech_lead"}, headers=_admin(client))
    # The same token: the type is read from the database, not the token.
    assert client.get(f"/api/staff/tickets/{billing}", headers=lead).status_code == 403
    assert client.get("/api/manager/tickets", params={"department": "all"}, headers=lead).status_code == 403
    assert billing not in _ids(client, lead)
    assert client.get("/api/manager/teams", headers=lead).status_code == 403
    assert client.get("/api/auth/me", headers=lead).json()["manager_type"] == "tech_lead"
    # A role change signs them out altogether.
    client.patch(f"/api/admin/users/{lead_id}", json={"role": "technician"}, headers=_admin(client))
    assert client.get("/api/manager/tickets", headers=lead).status_code == 401


def test_demoting_the_last_platform_lead_breaks_nothing(client):
    admin = _admin(client)
    for user in client.get("/api/admin/users", params={"role": "manager"}, headers=admin).json():
        if user["manager_type"] == "platform_lead":
            res = client.patch(f"/api/admin/users/{user['user_id']}", json={"manager_type": "tech_lead"}, headers=admin)
            assert res.status_code == 200
    assert not _sql("SELECT 1 FROM staff WHERE manager_type = 'platform_lead'")
    # A Tech Lead with no department: an empty scope, not an error.
    former = _login(client, seed_data.DEMO_PLATFORM_LEAD["email"], seed_data.DEMO_PLATFORM_LEAD["password"])
    ticket = _raise(client, "ISSUE")
    assert _ids(client, former) == set()
    assert client.get("/api/manager/dashboard", headers=former).json()["by_status"]["total"] == 0
    assert client.get("/api/manager/technicians", headers=former).json()["technicians"] == []
    manager = _login(client, "manager@example.com", "manager-demo-pass")
    assert ticket in _ids(client, manager)
    assert client.get("/api/admin/users", headers=admin).status_code == 200


@pytest.mark.parametrize("path", ["/api/manager/teams", "/api/manager/dashboard?department=all",
                                  "/api/manager/tickets?department=all", "/api/manager/technicians",
                                  "/api/manager/departments"])
def test_the_admin_gets_403_on_manager_pages(client, path):
    assert client.get(path, headers=_admin(client)).status_code == 403
