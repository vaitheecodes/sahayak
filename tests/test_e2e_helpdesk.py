"""End-to-end: the whole help-desk journey through the real app.

Customer chats with the AI -> the AI can't resolve it -> the chat escalates
to an unassigned ticket with an AI summary and suggested steps -> a
technician claims it, replies publicly and adds a private note -> the
customer sees the reply but not the note -> other customers report the
same problem -> the manager sees the correlated incident and confirms it
-> the first customer sees the neutral incident notice.

Everything is real (FastAPI app, LangGraph routing pipeline, SQLite,
background correlation, permissions, the neutral test KB of the fictional
"Brightdesk HR", tests/kb_fixture.py) except the language model:
provider.complete is replaced by a scripted fake that answers each AI
operation the way a well-behaved model would. Only the model is mocked.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from backend import db, graph, main, runtime, seed_data
from tests import kb_fixture
from backend.ai_service import provider

PRIVATE_NOTE = "Internal: three customers on app 4.2 — check the geofence service first."


class _ScriptedModel:
    """Answers by operation, recognised from the trusted instructions."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, messages, **kwargs):
        system, user = messages[0]["content"], messages[1]["content"]
        if "You classify support tickets" in system:
            self.calls.append("categorize")
            return json.dumps({"category": "ISSUE", "confidence": 0.92})
        if "helpful customer support agent" in system or "support assistant for Brightdesk HR" in system:
            self.calls.append("answer")
            return "Please allow location access for the app in your phone settings, then clock in again."
        if "Decide whether the customer's new message is a CONTINUATION" in system:
            self.calls.append("continuation")
            return json.dumps({"is_continuation": False})
        if "taking over a chat" in system:
            self.calls.append("summarize_escalation")
            return json.dumps({
                "issue": "Clock-in shows a location error since 10:00.",
                "tried": ["Allowed location access for the app."],
                "findings": ["Android phone", "App 4.2"],
                "unresolved_questions": ["Does the company use geofencing for clock-in?"],
            })
        if "Suggest 2-5 concrete next steps" in system:
            self.calls.append("suggest_steps")
            # The second step's port isn't in the KB entry: it is dropped.
            return json.dumps({"steps": ["Allow location access for the app in the phone settings.",
                                         "Confirm outbound 443 to the geofence server.",
                                         "Check whether the company uses geofencing for clock-in."]})
        if "spot incidents" in system:
            self.calls.append("correlate")
            ids = re.findall(r"ticket_id: (\S+)", user)
            return json.dumps({
                "is_related": True, "related_ticket_ids": ids, "title": "Clock-in location errors",
                "why_related": "Same symptom from different customers within minutes.",
                "observed_facts": ["Several customers report a location error at clock-in since about 10:00"],
                "hypotheses": ["A problem with the geofence service"],
                "confidence": 0.82, "confidence_reasons": ["Same component", "Same time window"],
                "suggested_next_steps": ["Check the geofence service"], "candidate_departments": ["Product Support"],
            })
        if "concise summary of a possible incident" in system:
            self.calls.append("summarize_incident")
            return json.dumps({"title": "Clock-in location errors",
                               "summary": "Several customers report a location error at clock-in since 10:00."})
        raise AssertionError(f"Unexpected AI operation: {system[:80]}")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    model = _ScriptedModel()
    monkeypatch.setattr(provider, "complete", model)
    with TestClient(main.app) as c:
        kb_fixture.load()  # after startup, which reloads the settings
        runtime.set_graph(graph.build_graph())  # the real routing pipeline
        c.model = model
        yield c


def _bearer(res):
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _signup(client, name):
    return _bearer(client.post("/api/auth/customer/signup", json={
        "name": name, "email": f"{name.split()[0].lower()}@e2e.example.com", "password": "e2e-password"}))


def _staff(client, role):
    (p,) = [p for p in seed_data.DEMO_STAFF if p["role"] == role]
    return _bearer(client.post("/api/auth/login", json={"email": p["email"], "password": p["password"]}))


def test_customer_to_technician_to_manager_journey(client):
    # --- 1. Customer chats with the AI, which answers -----------------------
    ana = _signup(client, "Ana Ruiz")
    chat = client.post("/api/chats", json={"issue": "Clock-in shows a location error since 10:00 today"},
                       headers=ana).json()
    assert chat["status"] == "active"
    assert chat["messages"][-1]["content"].startswith("Please allow location access")

    # --- 2. The AI's answer doesn't fix it -> escalation --------------------
    chat = client.post(f"/api/chats/{chat['session_id']}/messages",
                       json={"message": "I allowed it but it's still not working"}, headers=ana).json()
    assert chat["status"] == "escalated"
    ticket_id = chat["ticket_id"]
    assert ticket_id in chat["messages"][-1]["content"]          # customer told the reference
    assert "won't need to repeat" in chat["messages"][-1]["content"]

    # --- 3. Unassigned queue, with the AI hand-off for the technician -------
    tech = _staff(client, "technician")
    queue = client.get("/api/staff/tickets?view=unassigned", headers=tech).json()
    (row,) = [t for t in queue if t["ticket_id"] == ticket_id]
    assert row["assignee_name"] is None and row["status"] == "open"
    workspace = client.get(f"/api/staff/tickets/{ticket_id}", headers=tech).json()
    assert workspace["ai"]["summary"]["issue"] == "Clock-in shows a location error since 10:00."
    assert workspace["ai"]["suggestions"] == ["Allow location access for the app in the phone settings.",
                                              "Check whether the company uses geofencing for clock-in."]
    assert [m["role"] for m in workspace["chat"]["transcript"]] == ["customer", "ai", "customer", "ai"]

    # --- 4. Technician claims, replies publicly, adds a private note --------
    assert client.post(f"/api/staff/tickets/{ticket_id}/claim", headers=tech).status_code == 200
    reply = client.post(f"/api/staff/tickets/{ticket_id}/messages", headers=tech, json={
        "body": "Thanks Ana — could you send a screenshot of the error and the app log?",
        "visibility": "public_reply", "set_status": "pending_customer"})
    assert reply.status_code == 200, reply.text
    note = client.post(f"/api/staff/tickets/{ticket_id}/messages", headers=tech,
                       json={"body": PRIVATE_NOTE, "visibility": "internal_note"})
    assert note.status_code == 200

    # --- 5. Customer sees the reply, never the note or the AI internals -----
    detail = client.get(f"/api/tickets/{ticket_id}", headers=ana)
    body = detail.text
    messages = detail.json()["messages"]
    assert any(m["sender"] == "staff" and "app log" in m["message"] for m in messages)
    assert PRIVATE_NOTE not in body
    assert "Check whether the company uses geofencing" not in body
    assert detail.json()["ticket"]["status"] == "pending_customer"
    reply = client.post(f"/api/tickets/{ticket_id}/reply", json={"message": "Log attached shortly."}, headers=ana)
    assert reply.json()["status"] == "open"                      # back with the support team

    # --- 6. Other customers report the same problem -------------------------
    for name in ("Ben Okafor", "Chen Li"):
        res = client.post("/api/tickets", headers=_signup(client, name), json={
            "subject": "Clock-in location error",
            "description": "Our staff get a location error at clock-in since 10:00 and it is not working.",
            "priority": "high"})
        assert res.status_code == 200 and res.json()["status"] == "open"
    assert "correlate" in client.model.calls                     # background correlation ran

    # --- 7. Manager sees the correlated incident and confirms it ------------
    manager = _staff(client, "manager")                          # Product Support department
    (incident,) = client.get("/api/incidents", headers=manager).json()
    assert incident["ticket_count"] == 3 and incident["customer_count"] == 3
    assert [d["name"] for d in incident["departments"]] == ["Product Support"]
    detail = client.get(f"/api/incidents/{incident['incident_id']}", headers=manager).json()
    assert ticket_id in {t["ticket_id"] for t in detail["tickets"]}
    assert detail["summary"]["observed_facts"] and detail["summary"]["hypotheses"]
    assert client.get(f"/api/staff/tickets/{ticket_id}", headers=manager).status_code == 200
    confirmed = client.post(f"/api/incidents/{incident['incident_id']}/review", headers=manager,
                            json={"action": "confirm", "note": "Geofence service issue confirmed with the platform team."})
    assert confirmed.json()["status"] == "confirmed"

    # --- 8. Customer sees a neutral notice; nothing was closed or merged ----
    detail = client.get(f"/api/tickets/{ticket_id}", headers=ana).json()
    assert detail["incident_notice"].startswith("We're aware of this issue")
    assert detail["ticket"]["status"] == "open"

    # --- 9. It's all on the record ------------------------------------------
    admin = _bearer(client.post("/api/auth/login", json={"email": "admin@example.com",
                                                         "password": "admin-dev-password"}))
    actions = {e["action"] for e in client.get("/api/admin/audit", params={"limit": 200},
                                               headers=admin).json()["events"]}
    assert {"ticket.claimed", "ticket.status_changed", "ticket.assignment_changed", "incident.confirm"} <= actions
