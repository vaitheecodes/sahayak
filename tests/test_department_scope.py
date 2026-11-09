"""Who sees what since the role-based layout:

- A manager sees only their own department (the one owning a ticket's or
  chat's category), in lists, counts and by direct id: reassign/priority
  outside it 403, the staff ticket view 403, another department's chat
  404, and reassigning goes only to technicians who work the department.
- A technician's dashboard counts only their own tickets.
- /api/staff/chats is for technicians and managers: customers and the
  admin get 403, and customer endpoints never carry staff-only fields.

The demo manager runs Product Support (SETUP/USAGE/ISSUE/INTEGRATION);
ACCOUNT tickets belong to Accounts & Billing. Runs on SQLite and, with
DB_BACKEND=postgres, on Postgres. The pipeline is a stub.
"""

from __future__ import annotations

import itertools
import json

import pytest
from fastapi.testclient import TestClient

from backend import db, main, runtime, seed_data
from backend.ai_service import suggest_steps
from backend.ai_service import summarize_conversation as summaries
from backend.ai_service.schemas import HandoffSummary, SuggestedSteps

_counter = itertools.count()


class _Graph:
    """Routes per the next category set on it: human for tickets, and an
    AI answer for chats when `answer` is set."""

    category = "ISSUE"
    answer = False

    def invoke(self, state):
        if self.answer:
            return {"route": "ai", "category": self.category, "confidence": 0.95,
                    "ai_response": "Open Settings and pick Restart.", "clarification_attempts": 0}
        return {"route": "human", "category": self.category, "confidence": 0.4, "clarification_attempts": 0}


@pytest.fixture()
def graph():
    return _Graph()


@pytest.fixture()
def client(tmp_path, monkeypatch, graph):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(summaries, "summarize_escalation", lambda transcript, reason: HandoffSummary(
        issue="Cannot sign in.", tried=[], findings=[], unresolved_questions=["Which screen?"]))
    monkeypatch.setattr(suggest_steps, "suggest_steps", lambda data: SuggestedSteps(steps=["Check the sign-in log."]))
    with TestClient(main.app) as c:
        runtime.set_graph(graph)
        yield c


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _login(client, email, password):
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return _bearer(res.json()["token"])


def _demo(client, role):
    (p,) = [p for p in seed_data.DEMO_STAFF if p["role"] == role]
    return _login(client, p["email"], p["password"])


def _admin(client):
    return _login(client, "admin@example.com", "admin-dev-password")


def _customer(client):
    res = client.post("/api/auth/customer/signup", json={
        "name": "Dana Smith", "email": f"scope-{next(_counter)}@example.com", "password": "password123"})
    return _bearer(res.json()["token"])


def _department_id(client, name):
    departments = client.get("/api/admin/departments", headers=_admin(client)).json()["departments"]
    return next(d["department_id"] for d in departments if d["name"] == name)


def _technician(client, department=None):
    email = f"tech-{next(_counter)}@example.com"
    res = client.post("/api/admin/staff", json={
        "name": f"Tech {email}", "email": email, "role": "technician",
        "department_id": _department_id(client, department) if department else None}, headers=_admin(client))
    assert res.status_code == 200, res.text
    temp = res.json()["temporary_password"]
    headers = _login(client, email, temp)
    client.post("/api/auth/change-password",
                json={"current_password": temp, "new_password": "real-pass-456"}, headers=headers)
    return headers, res.json()["staff_id"]


def _raise(client, graph, customer, category):
    graph.category = category
    res = client.post("/api/tickets", json={
        "subject": f"{category} problem", "description": "Something is wrong with it.", "priority": "medium"},
        headers=customer)
    assert res.status_code == 200, res.text
    return res.json()["ticket_id"]


# ---------------------------------------------------------------------------
# Manager: own department only
# ---------------------------------------------------------------------------
def test_manager_lists_and_counts_only_their_department(client, graph):
    customer = _customer(client)
    mine = _raise(client, graph, customer, "ISSUE")
    other = _raise(client, graph, customer, "ACCOUNT")
    manager = _demo(client, "manager")

    listed = client.get("/api/manager/tickets", headers=manager).json()
    assert listed["department"]["name"] == "Product Support"
    ids = {t["ticket_id"] for t in listed["tickets"]}
    assert mine in ids and other not in ids

    kpis = client.get("/api/manager/dashboard?period=this_year", headers=manager).json()["kpis"]
    assert kpis["open"] == 1 and kpis["unassigned"] == 1
    sla_ids = json.dumps(client.get("/api/manager/sla?period=this_year", headers=manager).json())
    assert other not in sla_ids


def test_manager_cannot_act_on_another_departments_ticket_by_id(client, graph):
    customer = _customer(client)
    other = _raise(client, graph, customer, "ACCOUNT")
    manager = _demo(client, "manager")
    _, billing_tech = _technician(client, "Accounts & Billing")

    assert client.get(f"/api/staff/tickets/{other}", headers=manager).status_code == 403
    assert client.post(f"/api/manager/tickets/{other}/reassign", json={"technician_id": billing_tech},
                       headers=manager).status_code == 403
    assert client.post(f"/api/manager/tickets/{other}/priority", json={"priority": "urgent"},
                       headers=manager).status_code == 403
    assert client.post("/api/manager/tickets/TKT-nope/priority", json={"priority": "low"},
                       headers=manager).status_code == 404
    (row,) = [dict(r) for r in db.get_connection().execute(
        "SELECT priority, assigned_technician_id FROM tickets WHERE ticket_id = ?", (other,))]
    assert row == {"priority": "medium", "assigned_technician_id": None}


def test_manager_reassigns_only_to_their_departments_technicians(client, graph):
    ticket = _raise(client, graph, _customer(client), "ISSUE")
    manager = _demo(client, "manager")
    _, outsider = _technician(client, "Accounts & Billing")
    _, unplaced = _technician(client)
    _, insider = _technician(client, "Product Support")

    technicians = {t["staff_id"] for t in client.get("/api/manager/technicians", headers=manager).json()["technicians"]}
    assert insider in technicians and outsider not in technicians and unplaced not in technicians

    for staff_id in (outsider, unplaced):
        res = client.post(f"/api/manager/tickets/{ticket}/reassign", json={"technician_id": staff_id},
                          headers=manager)
        assert res.status_code == 400, res.text
    res = client.post(f"/api/manager/tickets/{ticket}/reassign", json={"technician_id": insider}, headers=manager)
    assert res.status_code == 200, res.text
    listed = client.get("/api/manager/tickets", headers=manager).json()["tickets"]
    assert next(t for t in listed if t["ticket_id"] == ticket)["assigned_technician_id"] == insider


# ---------------------------------------------------------------------------
# Technician dashboard: own tickets only
# ---------------------------------------------------------------------------
def test_technician_dashboard_counts_only_their_own_tickets(client, graph):
    customer = _customer(client)
    me, my_id = _technician(client)
    someone_else, _ = _technician(client)
    t1, t2, theirs, _unclaimed = (_raise(client, graph, customer, "ISSUE") for _ in range(4))
    for headers, ticket in ((me, t1), (me, t2), (someone_else, theirs)):
        assert client.post(f"/api/staff/tickets/{ticket}/claim", headers=headers).status_code == 200
    res = client.post(f"/api/staff/tickets/{t2}/status", json={"status": "pending_customer"}, headers=me)
    assert res.status_code == 200, res.text

    dash = client.get("/api/staff/dashboard?period=this_week", headers=me).json()
    assert dash["cards"]["assigned"] == 2
    assert dash["cards"]["in_progress"] == 1
    assert dash["cards"]["pending_customer"] == 1
    assert {r["ticket_id"] for r in dash["attention"]} == {t1, t2}
    assert dash["period"]["preset"] == "this_week"

    # Managers have their own dashboard; the technician one is technicians only.
    assert client.get("/api/staff/dashboard", headers=_demo(client, "manager")).status_code == 403
    assert client.get("/api/staff/dashboard?period=last_decade", headers=me).status_code == 422


# ---------------------------------------------------------------------------
# Staff chats
# ---------------------------------------------------------------------------
def _chat(client, graph, customer, category, escalate):
    graph.category, graph.answer = category, not escalate
    res = client.post("/api/chats", json={"issue": f"{category} help please"}, headers=customer)
    assert res.status_code == 200, res.text
    graph.answer = False
    return res.json()


def test_staff_chats_are_for_staff_and_department_limited(client, graph):
    customer = _customer(client)
    ours = _chat(client, graph, customer, "SETUP", escalate=False)
    theirs = _chat(client, graph, customer, "ACCOUNT", escalate=True)
    assert ours["status"] == "active" and theirs["status"] == "escalated"

    assert client.get("/api/staff/chats", headers=customer).status_code == 403
    assert client.get("/api/staff/chats", headers=_admin(client)).status_code == 403
    assert client.get(f"/api/staff/chats/{ours['session_id']}", headers=_admin(client)).status_code == 403
    assert client.get("/api/staff/chats").status_code == 401

    technician = _demo(client, "technician")
    assert [c["session_id"] for c in client.get("/api/staff/chats?filter=active", headers=technician).json()] \
        == [ours["session_id"]]
    escalated = client.get("/api/staff/chats?filter=escalated", headers=technician).json()
    assert [c["ticket_id"] for c in escalated] == [theirs["ticket_id"]]
    detail = client.get(f"/api/staff/chats/{theirs['session_id']}", headers=technician).json()
    assert detail["ticket_id"] == theirs["ticket_id"]
    assert detail["messages"][0]["content"] == "ACCOUNT help please"

    manager = _demo(client, "manager")
    assert client.get("/api/staff/chats?filter=escalated", headers=manager).json() == []
    assert client.get(f"/api/staff/chats/{theirs['session_id']}", headers=manager).status_code == 404
    assert client.get(f"/api/staff/chats/{ours['session_id']}", headers=manager).status_code == 200

    # The customer's own views never carry the staff hand-off.
    body = json.dumps([client.get(f"/api/chats/{theirs['session_id']}", headers=customer).json(),
                       client.get(f"/api/tickets/{theirs['ticket_id']}", headers=customer).json()])
    assert "ai_suggestions" not in body and "Check the sign-in log." not in body
