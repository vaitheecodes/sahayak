"""Who can reach what after the admin role was slimmed down.

- The admin runs people and the system only: Users, Departments,
  Settings and the Activity log. Dashboards, tickets, SLA, reassign, the
  ticket workspace, chats, Chat Reviews, Incidents and Try a Ticket are
  403 for the admin; the old admin report/ticket endpoints are gone.
- Chat Reviews: technicians and managers.
- Incidents: managers (technicians only the ones assigned to them).
- Try a Ticket: technicians and managers, at /api/try-a-ticket.
- Unanswered questions (KB gaps): managers only, question text and count.
- Routing policy: public and read-only (the /docs page).
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from backend import db, main, runtime, seed_data

_counter = itertools.count()

# Any id will do: the role check runs before the incident is looked up.
_INCIDENT = "INC-doesnotexist"

INCIDENT_ENDPOINTS = [
    ("get", "/api/incidents", None),
    ("get", f"/api/incidents/{_INCIDENT}", None),
    ("post", f"/api/incidents/{_INCIDENT}/review", {"action": "confirm", "note": "x"}),
    ("put", f"/api/incidents/{_INCIDENT}/departments", {"department_ids": []}),
    ("put", f"/api/incidents/{_INCIDENT}/assignee", {"technician_id": None}),
    ("post", "/api/incidents/run", None),
    ("post", f"/api/incidents/{_INCIDENT}/resolution/draft",
     {"resolution_note": "Fixed", "fixed_at": "2026-01-01T00:00:00+00:00"}),
    ("put", f"/api/incidents/{_INCIDENT}/resolution/summary", {"customer_summary": "x"}),
    ("post", f"/api/incidents/{_INCIDENT}/resolution/send", {"customer_summary": "x"}),
    ("put", f"/api/incidents/{_INCIDENT}/visibility", {"visibility": "public"}),
]

CHAT_REVIEW_ENDPOINTS = [
    ("get", "/api/chat-reviews", None),
    ("post", "/api/chat-reviews/REV-doesnotexist", {"status": "verified"}),
]

TRY_A_TICKET = ("post", "/api/try-a-ticket", {"ticket_text": "agent offline"})


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    with TestClient(main.app) as c:
        yield c


def _bearer(res):
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _admin(client):
    return _bearer(client.post("/api/auth/login", json={
        "email": "admin@example.com", "password": "admin-dev-password"}))


def _demo(client, role):
    (p,) = [p for p in seed_data.DEMO_STAFF if p["role"] == role]
    return _bearer(client.post("/api/auth/login", json={"email": p["email"], "password": p["password"]}))


def _customer(client):
    return _bearer(client.post("/api/auth/customer/signup", json={
        "name": "Scope Tester", "email": f"scope-{next(_counter)}@example.com", "password": "password123"}))


def _call(client, endpoint, headers):
    method, path, body = endpoint
    kwargs = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    return getattr(client, method)(path, **kwargs)


# ---------------------------------------------------------------------------
# Removed from the admin
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("endpoint", INCIDENT_ENDPOINTS, ids=lambda e: f"{e[0]} {e[1]}")
def test_admin_gets_403_on_every_incident_endpoint(client, endpoint):
    assert _call(client, endpoint, _admin(client)).status_code == 403


@pytest.mark.parametrize("endpoint", CHAT_REVIEW_ENDPOINTS, ids=lambda e: f"{e[0]} {e[1]}")
def test_admin_gets_403_on_chat_reviews(client, endpoint):
    assert _call(client, endpoint, _admin(client)).status_code == 403


def test_admin_gets_403_on_try_a_ticket(client):
    assert _call(client, TRY_A_TICKET, _admin(client)).status_code == 403


def test_admin_simulator_endpoint_is_gone(client):
    res = client.post("/api/admin/simulate-ticket", json={"ticket_text": "x"}, headers=_admin(client))
    assert res.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Still reachable by the right roles
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["technician", "manager"])
def test_technicians_and_managers_use_chat_reviews(client, role):
    headers = _demo(client, role)
    assert client.get("/api/chat-reviews", headers=headers).status_code == 200
    # Past the role check: an unknown review is a 404, not a 403.
    res = client.post("/api/chat-reviews/REV-doesnotexist", json={"status": "verified"}, headers=headers)
    assert res.status_code == 404


def test_customers_cannot_use_chat_reviews(client):
    for endpoint in CHAT_REVIEW_ENDPOINTS:
        assert _call(client, endpoint, _customer(client)).status_code == 403


def test_managers_use_incidents(client):
    manager = _demo(client, "manager")
    assert client.get("/api/incidents", headers=manager).status_code == 200
    assert client.post("/api/incidents/run", headers=manager).status_code == 200
    assert client.get(f"/api/incidents/{_INCIDENT}", headers=manager).status_code == 404


def test_technicians_see_only_assigned_incidents_and_cannot_manage_them(client):
    tech = _demo(client, "technician")
    assert client.get("/api/incidents", headers=tech).json() == []
    for endpoint in INCIDENT_ENDPOINTS:
        method, path, _ = endpoint
        if path.endswith(("/review", "/departments", "/assignee", "/run", "/visibility")):
            assert _call(client, endpoint, tech).status_code == 403, path


def test_customers_cannot_use_incidents(client):
    customer = _customer(client)
    for endpoint in INCIDENT_ENDPOINTS:
        assert _call(client, endpoint, customer).status_code == 403, endpoint[1]


@pytest.mark.parametrize("role", ["technician", "manager"])
def test_staff_can_try_a_ticket(client, monkeypatch, role):
    seen = []

    class _Graph:
        def invoke(self, state):
            seen.append(state)
            return {**state, "category": "SETUP", "confidence": 0.9, "route": "ai"}

    monkeypatch.setattr(runtime, "get_graph", lambda: _Graph())
    res = _call(client, TRY_A_TICKET, _demo(client, role))
    assert res.status_code == 200, res.text
    assert res.json()["route"] == "ai"
    assert seen[0]["ticket_id"].startswith("SIM-")
    # Nothing is saved.
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM tickets WHERE ticket_id LIKE 'SIM-%'").fetchone()[0] == 0
    finally:
        conn.close()


def test_customers_cannot_try_a_ticket(client):
    assert _call(client, TRY_A_TICKET, _customer(client)).status_code == 403


def test_try_a_ticket_needs_a_login(client):
    assert client.post("/api/try-a-ticket", json={"ticket_text": "x"}).status_code == 401


# ---------------------------------------------------------------------------
# Routing policy: public, read-only
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/api/public/routing-policy", "/api/debug/routing-policy"])
def test_routing_policy_needs_no_login(client, path):
    res = client.get(path)
    assert res.status_code == 200
    assert {"confidence_threshold", "high_risk_categories", "decision_order"} <= set(res.json())


def test_routing_policy_is_read_only(client):
    assert client.post("/api/public/routing-policy", json={}).status_code == 405


# ---------------------------------------------------------------------------
# What the admin keeps
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "/api/admin/users", "/api/admin/departments", "/api/admin/settings", "/api/admin/audit",
])
def test_admin_keeps_its_pages(client, path):
    assert client.get(path, headers=_admin(client)).status_code == 200


@pytest.mark.parametrize("path", ["/api/admin/users", "/api/admin/departments", "/api/admin/audit"])
@pytest.mark.parametrize("role", ["technician", "manager"])
def test_admin_pages_stay_admin_only(client, path, role):
    assert client.get(path, headers=_demo(client, role)).status_code == 403


# Dashboards, SLA, ticket lists, reassign / priority, the ticket workspace,
# chats: the managers' and technicians'. The admin gets 403 on every one.
NOT_FOR_ADMIN = [
    ("get", "/api/manager/dashboard", None),
    ("get", "/api/manager/sla", None),
    ("get", "/api/manager/tickets", None),
    ("get", "/api/manager/technicians", None),
    ("get", "/api/manager/unanswered", None),
    ("post", "/api/manager/tickets/TKT-x/reassign", {"technician_id": None}),
    ("post", "/api/manager/tickets/TKT-x/priority", {"priority": "high"}),
    ("get", "/api/staff/dashboard", None),
    ("get", "/api/staff/tickets", None),
    ("get", "/api/staff/tickets/counts", None),
    ("get", "/api/staff/tickets/TKT-x", None),
    ("get", "/api/staff/chats", None),
    ("get", "/api/staff/chats/CHAT-x", None),
]


@pytest.mark.parametrize("endpoint", NOT_FOR_ADMIN, ids=lambda e: f"{e[0]} {e[1]}")
def test_admin_gets_403_on_dashboards_sla_tickets_reassign_and_chats(client, endpoint):
    assert _call(client, endpoint, _admin(client)).status_code == 403


@pytest.mark.parametrize("path", ["/api/admin/dashboard", "/api/admin/sla", "/api/admin/tickets",
                                  "/api/admin/technicians"])
def test_the_old_admin_report_and_ticket_endpoints_are_gone(client, path):
    assert client.get(path, headers=_admin(client)).status_code == 404
    res = client.post("/api/admin/tickets/TKT-x/reassign", headers=_admin(client), json={"technician_id": None})
    assert res.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Unanswered questions: managers only, question text and count
# ---------------------------------------------------------------------------
def _save_unanswered(*questions):
    conn = db.get_connection()
    try:
        for n, q in enumerate(questions):
            conn.execute("INSERT INTO kb_unanswered (unanswered_id, question, channel, conversation_id, reason, "
                         "created_at) VALUES (?, ?, 'chat', ?, 'no_guide', ?)",
                         (f"UQ-{n}", q, f"CHAT-{n}", f"2026-01-01T00:00:0{n}+00:00"))
        conn.commit()
    finally:
        conn.close()


def test_unanswered_questions_are_403_for_the_admin_technicians_and_customers(client):
    for headers in (_admin(client), _demo(client, "technician"), _customer(client)):
        assert client.get("/api/manager/unanswered", headers=headers).status_code == 403
    assert client.get("/api/manager/unanswered").status_code == 401
    # The admin's old URL is gone.
    assert client.get("/api/admin/unanswered", headers=_admin(client)).status_code in (404, 405)


def test_managers_get_question_text_and_count_only_most_asked_first(client):
    _save_unanswered("how do I add a shift rota", "How do I add a  shift rota", "where is the audit log")
    lead = _bearer(client.post("/api/auth/login", json={
        "email": seed_data.DEMO_PLATFORM_LEAD["email"], "password": seed_data.DEMO_PLATFORM_LEAD["password"]}))
    for headers in (_demo(client, "manager"), lead):
        body = client.get("/api/manager/unanswered", headers=headers).json()
        assert body["total"] == 3
        assert [(q["question"].lower().split()[:3], q["count"]) for q in body["questions"]] == [
            (["how", "do", "i"], 2), (["where", "is", "the"], 1)]
        # No customer, chat or ticket: nothing but the text and the count.
        assert all(set(q) == {"question", "count"} for q in body["questions"])
        assert "CHAT-" not in str(body)


def test_every_manager_type_may_see_the_list_and_nobody_else_has_the_permission():
    from backend import permissions

    assert all(permissions.allowed({"role": "manager", "manager_type": t}, "unanswered")
               for t in permissions.MANAGER_TYPES)
    assert permissions.allowed({"role": "technician"}, "unanswered") is None
