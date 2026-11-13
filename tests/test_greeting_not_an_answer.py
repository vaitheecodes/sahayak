"""A greeting, a clarifying question or a ticket notice is not an answer
(the live demo, chats CHAT-d1a22d8d and CHAT-beb0e26b):

- "Hi", then "... is not loading ..." is a first report: answered from the
  KB, never handed off as "the answer didn't work" (negation tag).
- After "Hi", the first real question is not a follow-up: no coverage check.
- "I don't have a guide" and the ticket number are ONE message.
- "My issue is solved" needs a real answer.
- Questions the KB didn't cover are saved for the managers' list (KB gaps).

Real app, LangGraph pipeline and SQLite on the neutral test KB; the model
is a scripted fake (tests/test_how_to_flow.py's).
"""

from __future__ import annotations

import pytest

from backend import chats, db, graph, seed_data
from backend.ai_service import chat_response
from tests.test_how_to_flow import ANSWER, _ai_lines, _chat, _customer, _send, client  # noqa: F401

NOT_LOADING = "My payslip is not showing for this month, the page is not loading. What should I do?"


def test_not_loading_after_hi_is_a_first_report_and_is_answered(client):
    headers = _customer(client)
    chat = _send(client, headers, _chat(client, headers, "Hi"), NOT_LOADING)
    assert chat["status"] == "active" and _ai_lines(chat)[-1] == ANSWER and chat["answered"]


def test_not_loading_after_a_real_answer_still_goes_to_a_person(client):
    headers = _customer(client)
    chat = _chat(client, headers, "My payslip is not showing for this month")
    assert _ai_lines(chat) == [ANSWER]
    chat = _send(client, headers, chat, "I did that, it's still not loading")
    assert chat["status"] == "escalated"


@pytest.mark.parametrize("answered, checked", [(False, False), (True, True)])
def test_only_a_message_after_a_real_answer_gets_the_coverage_check(client, monkeypatch, answered, checked):
    calls = []
    monkeypatch.setattr(chat_response, "covers_latest", lambda data: calls.append(1) or True)
    state = {"ticket_id": "CHAT-x", "customer_id": "C1", "channel": "chat", "answered": answered,
             "ticket_text": f"Customer: Hi\nAgent (AI): {chats.greeting()}\nCustomer: {NOT_LOADING}",
             "recent_ai_replies": [chats.greeting()]}
    state.update(graph.retrieve_kb_candidates(state))
    graph.generate_response(state)
    assert bool(calls) is checked


def test_no_guide_and_the_ticket_number_are_one_message(client):
    headers = _customer(client)
    chat = _send(client, headers, _chat(client, headers, "Hi"), "how do I add a performance review cycle")
    assert chat["status"] == "escalated"
    after = _ai_lines(chat)[1:]
    assert after == [after[0]] and after[0].startswith(chats.NO_GUIDE_LEAD) and chat["ticket_id"] in after[0]


def test_my_issue_is_solved_needs_a_real_answer(client):
    headers = _customer(client)
    chat = _chat(client, headers, "Hi")
    assert chat["answered"] is False
    assert client.post(f"/api/chats/{chat['session_id']}/resolve", headers=headers).status_code == 400


def test_no_guide_questions_are_saved_for_the_managers_list(client):
    for text in ("how do I add a performance review cycle", "How do I add a  performance review cycle",
                 "how do I set up shift rotas"):
        _chat(client, _customer(client), text)
    (p,) = [p for p in seed_data.DEMO_STAFF if p["role"] == "manager"]
    manager = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": p["email"], "password": p["password"]}).json()["token"]}
    rows = client.get("/api/manager/unanswered", headers=manager).json()["questions"]
    assert [r["count"] for r in rows] == [2, 1] and rows[0]["question"].lower().startswith("how do i add a")


def test_try_a_ticket_and_staff_save_no_unanswered_question(client):
    state = {"ticket_id": "SIM-1", "customer_id": "C1", "channel": "chat",
             "ticket_text": "Customer: how do I add a performance review cycle"}
    state.update(graph.retrieve_kb_candidates(state))
    graph.generate_response(state)
    conn = db.get_connection()
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM kb_unanswered").fetchone()["n"] == 0
    finally:
        conn.close()
    assert client.get("/api/manager/unanswered", headers=_customer(client)).status_code == 403
