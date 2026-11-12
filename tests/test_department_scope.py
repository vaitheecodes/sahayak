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
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend import db, main, runtime, seed_data, sla
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
    # The change revokes the temporary-password token.
    headers = {"Authorization": "Bearer " + client.post("/api/auth/change-password",
                json={"current_password": temp, "new_password": "real-pass-456"}, headers=headers).json()["token"]}
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


def test_seed_gives_an_existing_demo_technician_a_department(client):
    """A demo database from before technicians had departments: the next
    startup's seed fills the gap, so the demo manager can reassign."""
    (tech,) = [p for p in seed_data.DEMO_STAFF if p["role"] == "technician"]
    conn = db.get_connection()
    try:
        conn.execute("UPDATE staff SET department_id = NULL WHERE email = ?", (tech["email"],))
        conn.commit()
        seed_data.seed_demo_staff(conn)
        (row,) = conn.execute("SELECT d.name FROM staff s JOIN departments d ON d.department_id = s.department_id "
                              "WHERE s.email = ?", (tech["email"],)).fetchall()
    finally:
        conn.close()
    assert row["name"] == tech["department"]


# ---------------------------------------------------------------------------
# Technician Tickets: tab counts and Recently resolved
# ---------------------------------------------------------------------------
def test_tab_counts_and_recently_resolved_boundary(client, graph):
    customer = _customer(client)
    me, _ = _technician(client)
    unassigned, mine, done = (_raise(client, graph, customer, "ISSUE") for _ in range(3))
    for ticket in (mine, done):
        assert client.post(f"/api/staff/tickets/{ticket}/claim", headers=me).status_code == 200
    res = client.post(f"/api/staff/tickets/{done}/status", json={"status": "resolved"}, headers=me)
    assert res.status_code == 200, res.text

    counts = client.get("/api/staff/tickets/counts", headers=me).json()
    assert counts == {"unassigned": 1, "mine": 2, "open_pending": 2, "resolved": 1}
    assert [t["ticket_id"] for t in client.get("/api/staff/tickets?view=resolved", headers=me).json()] == [done]
    assert [t["ticket_id"] for t in client.get("/api/staff/tickets?view=unassigned", headers=me).json()] \
        == [unassigned]

    # 14 days: one resolved 13 days ago is still listed, one 15 days ago is not.
    recent = _raise(client, graph, customer, "ISSUE")
    client.post(f"/api/staff/tickets/{recent}/claim", headers=me)
    client.post(f"/api/staff/tickets/{recent}/status", json={"status": "resolved"}, headers=me)
    conn = db.get_connection()
    try:
        for ticket, days in ((done, 15), (recent, 13)):
            conn.execute("UPDATE tickets SET resolved_at = ? WHERE ticket_id = ?",
                         (sla.iso(sla.now() - timedelta(days=days)), ticket))
        conn.commit()
    finally:
        conn.close()
    listed = [t["ticket_id"] for t in client.get("/api/staff/tickets?view=resolved", headers=me).json()]
    assert listed == [recent]
    assert client.get("/api/staff/tickets/counts", headers=me).json()["resolved"] == 1


# ---------------------------------------------------------------------------
# An escalated chat and its ticket share one category, so the manager's chat
# scope and ticket scope agree (no "Open the ticket" link that 403s).
# ---------------------------------------------------------------------------
def _category_pair(session_id):
    conn = db.get_connection()
    try:
        (row,) = conn.execute(
            "SELECT COALESCE(s.category, s.requested_category) AS chat, "
            "COALESCE(t.category, t.requested_category) AS ticket FROM chat_sessions s "
            "JOIN tickets t ON t.ticket_id = s.escalated_ticket_id WHERE s.session_id = ?", (session_id,)).fetchall()
        return row["chat"], row["ticket"]
    finally:
        conn.close()


def test_escalated_chat_ticket_takes_the_chats_latest_category(client, graph):
    customer = _customer(client)
    manager = _demo(client, "manager")

    # Answered as SETUP, then the escalating turn is classified ACCOUNT.
    moved = _chat(client, graph, customer, "SETUP", escalate=False)
    graph.category = "ACCOUNT"
    res = client.post(f"/api/chats/{moved['session_id']}/messages",
                      json={"message": "It is still not working after that"}, headers=customer)
    assert res.status_code == 200 and res.json()["status"] == "escalated", res.text
    assert _category_pair(moved["session_id"]) == ("ACCOUNT", "ACCOUNT")
    # Neither is in Product Support: the chat is hidden, the ticket refused.
    assert client.get(f"/api/staff/chats/{moved['session_id']}", headers=manager).status_code == 404
    assert client.get(f"/api/staff/tickets/{res.json()['ticket_id']}", headers=manager).status_code == 403

    # "Raise a ticket" after an answer: both SETUP, and the link opens.
    kept = _chat(client, graph, customer, "SETUP", escalate=False)
    res = client.post(f"/api/chats/{kept['session_id']}/escalate", json={}, headers=customer)
    assert res.status_code == 200, res.text
    assert _category_pair(kept["session_id"]) == ("SETUP", "SETUP")
    detail = client.get(f"/api/staff/chats/{kept['session_id']}", headers=manager).json()
    assert client.get(f"/api/staff/tickets/{detail['ticket_id']}", headers=manager).status_code == 200


# ---------------------------------------------------------------------------
# Dashboards: created in the period by current status (New = open with
# nobody assigned), per-technician figures; kanban list filters keep scope
# ---------------------------------------------------------------------------
def _set(ticket_id, **columns):
    conn = db.get_connection()
    try:
        for column, value in columns.items():
            conn.execute(f"UPDATE tickets SET {column} = ? WHERE ticket_id = ?", (value, ticket_id))
        conn.commit()
    finally:
        conn.close()


def test_manager_dashboard_counts_created_tickets_by_status_and_technician(client, graph):
    customer = _customer(client)
    insider_headers, insider = _technician(client, "Product Support")
    new, picked, waiting, done = (_raise(client, graph, customer, "ISSUE") for _ in range(4))
    _raise(client, graph, customer, "ACCOUNT")  # another department: never counted
    old = _raise(client, graph, customer, "ISSUE")
    _set(old, created_at=sla.iso(sla.now() - timedelta(days=400)))  # before this year
    manager = _demo(client, "manager")
    for ticket in (picked, waiting, done):
        res = client.post(f"/api/manager/tickets/{ticket}/reassign", json={"technician_id": insider}, headers=manager)
        assert res.status_code == 200, res.text
    client.post(f"/api/staff/tickets/{picked}/status", json={"status": "open"}, headers=insider_headers)
    client.post(f"/api/staff/tickets/{waiting}/status", json={"status": "pending_customer"}, headers=insider_headers)
    client.post(f"/api/staff/tickets/{done}/status", json={"status": "resolved"}, headers=insider_headers)

    data = client.get("/api/manager/dashboard?period=this_year", headers=manager).json()
    assert data["by_status"] == {"total": 4, "new": 1, "open": 1, "in_progress": 0, "pending_customer": 1,
                                 "resolved": 1, "closed": 0}
    assert sum(v for k, v in data["by_status"].items() if k != "total") == data["by_status"]["total"]
    assert data["created_sla"] == {"breached": 0, "at_risk": 0}  # SLA is off by default
    # The charts: created in the period by priority (adds up too) and per day.
    assert data["by_priority"] == {"low": 0, "medium": 4, "high": 0, "urgent": 0}
    assert sum(day["created"] for day in data["over_time"]) == 4
    (row,) = [w for w in data["technician_workload"] if w["technician_id"] == insider]
    assert row["open"] == 2 and row["resolved"] == 1 and row["breached"] == 0
    assert "avg_first_response_minutes" in row

    def ids(**filters):
        query = "&".join(f"{k}={v}" for k, v in filters.items())
        res = client.get(f"/api/manager/tickets?{query}", headers=manager)
        assert res.status_code == 200, res.text
        return {t["ticket_id"] for t in res.json()["tickets"]}

    assert ids(status="new", period="this_year") == {new}
    assert ids(status="open", assigned="true", period="this_year") == {picked}
    assert ids(period="this_year") == {new, picked, waiting, done}
    assert old in ids() and old not in ids(period="this_year")


def test_technician_dashboard_and_kanban_list_are_their_own_tickets(client, graph):
    customer = _customer(client)
    me, _ = _technician(client)
    other, _ = _technician(client)
    mine, theirs, unassigned = (_raise(client, graph, customer, "ISSUE") for _ in range(3))
    client.post(f"/api/staff/tickets/{mine}/claim", headers=me)
    client.post(f"/api/staff/tickets/{theirs}/claim", headers=other)

    data = client.get("/api/staff/dashboard?period=this_week", headers=me).json()
    assert data["by_status"]["total"] == 1 and data["by_status"]["in_progress"] == 1
    assert data["by_status"]["new"] == 0
    assert data["by_priority"]["medium"] == 1 and sum(data["by_priority"].values()) == 1
    assert sum(day["created"] for day in data["over_time"]) == 1

    def ids(**filters):
        query = "&".join(f"{k}={v}" for k, v in {"view": "mine", **filters}.items())
        res = client.get(f"/api/staff/tickets?{query}", headers=me)
        assert res.status_code == 200, res.text
        return [t["ticket_id"] for t in res.json()]

    assert ids(period="this_week") == [mine]
    assert ids(period="this_week", status="in_progress") == [mine]
    assert ids(period="this_week", status="new") == []
    # "new" on the unassigned view: the unclaimed ticket only.
    res = client.get("/api/staff/tickets?view=unassigned&status=new&period=this_week", headers=me)
    assert [t["ticket_id"] for t in res.json()] == [unassigned]
    _set(mine, created_at=sla.iso(sla.now() - timedelta(days=60)))
    assert ids(period="this_week") == []
    assert client.get("/api/staff/tickets?view=mine&period=last_decade", headers=me).status_code == 422


def _copies(template, count, *, minutes_ago, target_minutes, **columns):
    """`count` copies of a ticket row with an SLA of `target_minutes`,
    created `minutes_ago` (a second apart, newest first)."""
    conn = db.get_connection()
    try:
        row = dict(conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (template,)).fetchone())
        ids = []
        for i in range(count):
            ticket_id = f"{template}-{minutes_ago}-{i}"
            created = sla.now() - timedelta(minutes=minutes_ago, seconds=i)
            values = {**row, "ticket_id": ticket_id, "created_at": sla.iso(created), "first_response_at": None,
                      "sla_first_response_minutes": target_minutes, "sla_resolution_minutes": target_minutes,
                      "sla_first_response_due": sla.iso(created + timedelta(minutes=target_minutes)),
                      "sla_resolution_due": sla.iso(created + timedelta(minutes=target_minutes)), **columns}
            conn.execute(f"INSERT INTO tickets ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                         list(values.values()))
            ids.append(ticket_id)
        conn.commit()
        return set(ids)
    finally:
        conn.close()


def test_sla_counts_and_filter_cover_more_than_one_page(client, graph):
    """The SLA filter is applied on the server before the list limit (500
    for managers, 200 for support engineers): older breached tickets behind
    a full page of on-track ones are still found, and match the counts."""
    customer = _customer(client)
    headers, engineer = _technician(client, "Product Support")
    template = _raise(client, graph, customer, "ISSUE")
    _set(template, status="resolved")  # keeps the template out of the SLA counts
    mine = {"assigned_technician_id": engineer, "status": "in_progress", "route": "human"}
    breached = _copies(template, 30, minutes_ago=15, target_minutes=1, **mine)
    at_risk = _copies(template, 5, minutes_ago=50, target_minutes=60, **mine)
    _copies(template, 520, minutes_ago=0, target_minutes=600, **mine)  # newer and on track

    manager = _demo(client, "manager")
    data = client.get("/api/manager/dashboard?period=this_year", headers=manager).json()
    assert data["created_sla"] == {"breached": 30, "at_risk": 5}

    def manager_ids(state):
        res = client.get(f"/api/manager/tickets?period=this_year&sla={state}", headers=manager)
        assert res.status_code == 200, res.text
        return {t["ticket_id"] for t in res.json()["tickets"]}

    assert manager_ids("breached") == breached
    assert manager_ids("at_risk") == at_risk
    assert len(client.get("/api/manager/tickets?period=this_year", headers=manager).json()["tickets"]) == 500

    data = client.get("/api/staff/dashboard?period=this_year", headers=headers).json()
    assert data["created_sla"] == {"breached": 30, "at_risk": 5}
    res = client.get("/api/staff/tickets?view=mine&period=this_year&sla=breached", headers=headers)
    assert {t["ticket_id"] for t in res.json()} == breached
    assert all(t["sla"]["state"] == "breached" for t in res.json())
    assert len(client.get("/api/staff/tickets?view=mine&period=this_year", headers=headers).json()) == 200
    assert client.get("/api/staff/tickets?view=mine&sla=paused", headers=headers).status_code == 422
