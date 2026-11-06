"""KB entries with handling "escalate_with_info".

- handling and collect reach the retrieval index and the candidates.
- The reply gives numbered steps from the approved answer (the model's
  rewrite, or the answer's own lines when the rewrite asks a question or
  has no numbered steps), then the collect list and a fixed safety note;
  it never asks a question.
- The ticket is raised in the same turn: chat (escalated session +
  unassigned ticket), and a new email-style ticket (routed to a human).
- On the neutral test KB (tests/kb_fixture.py): the sign-in entry
  (KB-0005) takes a high-risk ACCOUNT request to its steps and a ticket,
  and an entry for one integration (Slack, KB-0007) stays unconfirmed
  until the customer mentions it.

Real temporary SQLite DB via FastAPI's TestClient; the pipeline is a stub
and the provider is disabled by tests/conftest.py unless a test stubs it.
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from backend import db, graph, kb_retrieval, kb_store, main, runtime, topic_terms
from backend.ai_service import chat_response, provider, summarize_ticket
from backend.ai_service.schemas import AnswerInput, HandoffSummary, KBCandidate
from tests import kb_fixture

_counter = itertools.count()

ANSWER = ("Support may ask for a HAR file. Right-click the page and choose Inspect.\n"
          "Chrome or Edge: turn on \"Preserve log\", then choose \"Save all as HAR with content\".\n"
          "A HAR file can contain cookies and tokens, so attach it only to your ticket.")
ENTRY = KBCandidate(kb_entry_id="KB-0901", category="ISSUE", intent="Report a page error with a HAR file",
                    instruction="invalid data provided error when saving a form", response=ANSWER,
                    score=0.9, handling="escalate_with_info",
                    collect=["Exact error text", "A HAR file of the failing attempt"])
STEPS = ("A HAR file helps our team see what failed.\n"
         "1. Right-click the page and choose Inspect.\n"
         "2. In Chrome or Edge, turn on \"Preserve log\" in the Network tab.\n"
         "3. Choose \"Save all as HAR with content\".")


def _data(**kwargs):
    return AnswerInput(ticket_text="Customer: invalid data provided when saving the form", kb_candidates=[ENTRY],
                       latest_message="invalid data provided when saving the form", **kwargs)


def _model(monkeypatch, *replies):
    calls = []

    def fake(instructions, blocks, operation="", **kwargs):
        calls.append((operation, blocks))
        reply = replies[min(len(calls), len(replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(provider, "complete_text", fake)
    return calls


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def test_handling_and_collect_reach_the_index():
    entry = {"kb_entry_id": "KB-0901", "title": "Zebra form errors", "category": "ISSUE",
             "handling": "escalate_with_info", "collect": ["Exact error text"],
             "questions": ["zebra add error one", "zebra add error two"], "answer": ANSWER, "steps": []}
    index = kb_retrieval.build_index(kb_store.retrieval_docs([entry]))
    (hit,) = graph._kb_candidates_to_dicts(index.search("zebra add error one"))
    assert hit["handling"] == "escalate_with_info" and hit["collect"] == ["Exact error text"]


def test_entries_default_to_answer():
    kb_fixture.load()
    (hit, *_) = kb_retrieval.retrieve_candidates("how do I apply for leave")
    assert hit.entry.handling == "answer" and hit.entry.collect == ()


# ---------------------------------------------------------------------------
# The reply
# ---------------------------------------------------------------------------
def test_numbered_steps_accepts_steps_and_drops_sensitive_sentences():
    assert chat_response.numbered_steps(STEPS) == STEPS
    with_note = STEPS + "\nNever share cookies or tokens."
    assert chat_response.numbered_steps(with_note) == STEPS
    assert chat_response.numbered_steps("Can you send a HAR file?\n1. a\n2. b") is None
    assert chat_response.numbered_steps("Just one paragraph, no steps.") is None


def test_steps_from_answer_numbers_the_answer_lines():
    steps = chat_response.steps_from_answer(ANSWER)
    assert steps.splitlines() == [
        "1. Support may ask for a HAR file. Right-click the page and choose Inspect.",
        "2. Chrome or Edge: turn on \"Preserve log\", then choose \"Save all as HAR with content\"."]


def test_info_request_gives_steps_collect_list_and_safety_note(monkeypatch):
    calls = _model(monkeypatch, "Hi there,\n" + STEPS)
    text = chat_response.info_request(_data()).text
    assert text.startswith("A HAR file helps") and "1. Right-click" in text
    assert "Please add these to your ticket:\n- Exact error text\n- A HAR file of the failing attempt" in text
    assert text.endswith(chat_response.INFO_SAFETY_NOTE)
    assert "?" not in text
    assert calls[0][0] == "info_request" and "Canonical guidance" in calls[0][1]["kb_guidance"]


@pytest.mark.parametrize("reply", [
    "Can you tell me which browser you use?",
    "Open developer tools and save the network log as a HAR file.",
    provider.AIError("empty", provider.AIFailure(kind="filter_rejected", operation="chat_filter")),
])
def test_info_request_falls_back_to_the_answer_lines(monkeypatch, reply):
    _model(monkeypatch, reply)
    text = chat_response.info_request(_data()).text
    assert text.startswith(chat_response.steps_from_answer(ANSWER))
    assert "?" not in text and text.endswith(chat_response.INFO_SAFETY_NOTE)


def test_info_request_provider_errors_still_raise(monkeypatch):
    _model(monkeypatch, provider.AIError("throttled", provider.AIFailure(kind="throttling", operation="x")))
    with pytest.raises(provider.AIError):
        chat_response.info_request(_data())


def test_info_request_email_format(monkeypatch):
    _model(monkeypatch, STEPS)
    text = chat_response.info_request(_data(reply_format="email", customer_name="Dana Smith")).text
    assert text.startswith("Hi Dana,") and "1. Right-click" in text and chat_response.INFO_SAFETY_NOTE in text


def test_generate_response_flags_needs_info_only_for_escalate_with_info(monkeypatch):
    _model(monkeypatch, STEPS)
    monkeypatch.setattr(chat_response, "answer", lambda data: chat_response.ChatReply(text="An answer."))
    state = {"ticket_text": "Customer: invalid data provided when saving the form",
             "kb_candidates": [ENTRY.model_dump()]}
    result = graph.generate_response(state)
    assert result["needs_info"] == {"kb_entry_id": "KB-0901", "collect": ENTRY.collect}
    assert "1. Right-click" in result["ai_response"]
    state["kb_candidates"] = [{**ENTRY.model_dump(), "handling": "answer"}]
    assert graph.generate_response(state) == {"ai_response": "An answer.", "needs_info": None}


# ---------------------------------------------------------------------------
# The ticket is raised in the same turn
# ---------------------------------------------------------------------------
class _StubGraph:
    def __init__(self, results):
        self._results = list(results)

    def invoke(self, state):
        return self._results.pop(0)


_CLARIFY = {"route": "clarify", "category": "USAGE", "confidence": 0.5,
            "ai_response": "Which part of the product is it?", "clarification_attempts": 1}
_NEEDS_INFO = {"route": "ai", "category": "USAGE", "confidence": 0.9, "clarification_attempts": 1,
               "ai_response": STEPS + "\n\n" + chat_response.INFO_SAFETY_NOTE,
               "needs_info": {"kb_entry_id": "KB-0901", "collect": ["Exact error text"]}}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(summarize_ticket, "summarize_ticket",
                        lambda thread, reason: HandoffSummary(issue="CASE SUMMARY"))
    with TestClient(main.app) as c:
        yield c


def _customer(client):
    res = client.post("/api/auth/customer/signup", json={
        "name": "Dana Smith", "email": f"info-{next(_counter)}@example.com", "password": "password123"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _query(sql, params=()):
    conn = db.get_connection()
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def test_chat_gives_the_steps_and_raises_the_ticket_in_the_same_turn(client):
    headers = _customer(client)
    runtime.set_graph(_StubGraph([_CLARIFY, _NEEDS_INFO]))
    chat = client.post("/api/chats", json={"issue": "i am facing issue in saving a form"}, headers=headers).json()
    assert chat["status"] == "active"
    res = client.post(f"/api/chats/{chat['session_id']}/messages",
                      json={"message": "invalid data provided when saving the form"}, headers=headers).json()
    assert res["status"] == "escalated" and res["ticket_id"]
    steps_msg, ticket_msg = res["messages"][-2:]
    assert steps_msg["role"] == "ai" and "1. Right-click" in steps_msg["content"]
    assert chat_response.INFO_SAFETY_NOTE in steps_msg["content"] and "?" not in steps_msg["content"]
    assert res["ticket_id"] in ticket_msg["content"]
    (ticket,) = _query("SELECT * FROM tickets WHERE ticket_id = ?", (res["ticket_id"],))
    assert (ticket["status"], ticket["route"], ticket["assigned_technician_id"]) == ("open", "human", None)
    assert "support needs details from the customer" in ticket["ticket_text"]


def test_new_ticket_with_needs_info_goes_to_the_team(client):
    headers = _customer(client)
    runtime.set_graph(_StubGraph([{**_NEEDS_INFO, "clarification_attempts": 0}]))
    res = client.post("/api/tickets", json={"subject": "Form error", "priority": "high",
                                            "description": "invalid data provided when saving the form"},
                      headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["route"], body["status"]) == ("human", "open")
    (ticket,) = _query("SELECT * FROM tickets WHERE ticket_id = ?", (body["ticket_id"],))
    assert ticket["route"] == "human" and ticket["assigned_technician_id"] is None


# ---------------------------------------------------------------------------
# On the neutral test KB
# ---------------------------------------------------------------------------
def test_a_high_risk_sign_in_problem_gets_the_entrys_steps_and_a_ticket():
    kb_fixture.load()
    text = "I am unable to sign in to brightdesk"
    state = {"ticket_text": f"Customer: {text}", "category": "ACCOUNT", "confidence": 0.5, "language_tags": [],
             "kb_candidates": graph.kb_candidates_for(text)}
    assert graph.decide_route(state)["route"] == "ai"
    assert "escalate_with_info" in graph.decide_route(state)["route_reason"]


@pytest.mark.parametrize("text, usable", [
    ("leave approvals are not posted to slack", True),
    ("approvals channel stopped getting posts", False),
])
def test_an_integration_entry_grounds_only_once_it_is_mentioned(text, usable):
    kb_fixture.load()
    state = {"ticket_text": f"Customer: {text}", "kb_candidates": graph.kb_candidates_for(text)}
    ok, unconfirmed = graph.grounding_candidates(state)
    ids = [c["kb_entry_id"] for c in ok] if usable else [c["kb_entry_id"] for c, _ in unconfirmed]
    assert "KB-0007" in ids
    if not usable:
        assert dict((c["kb_entry_id"], m) for c, m in unconfirmed)["KB-0007"] == {"Slack"}


def test_terms_match_their_aliases_as_whole_words():
    kb_fixture.load()
    assert topic_terms.mentioned("I need time off next week") == {"Leave"}
    assert topic_terms.mentioned("clock-in fails") == topic_terms.mentioned("clock in fails") == {"Attendance"}
    assert "iOS" in topic_terms.mentioned("the app on my iPad") and "iOS" not in topic_terms.mentioned("my bios")
