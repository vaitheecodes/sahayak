"""How-to questions: one fixed question when a detail is missing, then an
answer from the KB or a ticket, never invented steps and never a loop.

- Nothing to do named ("How do I add it"): ONE question asking what
  exactly, offering the product's confirmed modules, no ticket yet, no
  model call, never a record or an account identifier. After the answer:
  the KB entry, or "I don't have a guide for that yet" and a ticket
  ("not sure" too).
- Subject clear and a KB how-to on it: answered from that entry, even with
  extra words ("for last month as excel"); a one-word overlap on something
  else ("an overtime report for leave approvals" vs the apply-for-leave
  entry) doesn't count.
- Subject clear, no KB entry: the friendly reply and a ticket.
- Guides that apply to one platform each (the Android / iOS app guides)
  and neither named: "Android or iOS?", then the matching guide.
- The ticket form (email replies) takes the same path.

Real FastAPI app, LangGraph pipeline, KB retrieval and SQLite on the
neutral test KB (tests/kb_fixture.py); the language model is a scripted
fake.
"""

from __future__ import annotations

import itertools
import json

import pytest
from fastapi.testclient import TestClient

from backend import db, graph, main, runtime
from backend.ai_service import provider
from tests import kb_fixture

_counter = itertools.count()
MODULES = "Attendance, Expenses, Leave or Payroll"
TYPE_QUESTION = graph.HOW_TO_SUBJECT_QUESTION.format(verb="do", product="Brightdesk HR", options=MODULES)
# No numbered steps: grounding.py would drop steps the KB entry lacks.
ANSWER = "Here is how to do that from the guide."


class _Model:
    def __init__(self):
        self.category, self.confidence = "ISSUE", 0.8
        self.calls: list[tuple[str, str]] = []  # (operation, user prompt)

    def __call__(self, messages, **kwargs):
        system, user = messages[0]["content"], messages[1]["content"]
        if "You classify support tickets" in system:
            self.calls.append(("categorize", user))
            return json.dumps({"category": self.category, "confidence": self.confidence})
        if "support assistant for Brightdesk HR" in system or "helpful customer support agent" in system:
            self.calls.append(("answer", user))
            return ANSWER
        if "taking over" in system:
            self.calls.append(("handoff_summary", user))
            return json.dumps({"issue": "The customer wants to add something.", "tried": [], "findings": [],
                               "unresolved_questions": []})
        if "Suggest 2-5 concrete next steps" in system:
            self.calls.append(("suggest_steps", user))
            return json.dumps({"steps": ["Check the guide."]})
        self.calls.append(("other", system[:60]))
        raise AssertionError(f"Unexpected AI operation: {system[:80]}")

    def ops(self) -> list[str]:
        return [op for op, _ in self.calls]

    def answered_from(self) -> str:
        return next(user for op, user in self.calls if op == "answer")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    model = _Model()
    monkeypatch.setattr(provider, "complete", model)
    with TestClient(main.app) as c:
        kb_fixture.load()  # after startup, which reloads the settings
        runtime.set_graph(graph.build_graph())
        c.model = model
        yield c


def _customer(client):
    res = client.post("/api/auth/customer/signup", json={
        "name": "Dana Smith", "email": f"howto-{next(_counter)}@example.com", "password": "password123"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _chat(client, headers, issue):
    res = client.post("/api/chats", json={"issue": issue}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _send(client, headers, chat, message):
    res = client.post(f"/api/chats/{chat['session_id']}/messages", json={"message": message}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _ai_lines(chat):
    return [m["content"] for m in chat["messages"] if m["role"] == "ai"]


def _usable(question: str) -> list[str]:
    text = f"Customer: {question}"
    state = {"ticket_text": text}
    state.update(graph.retrieve_kb_candidates(state))
    usable, _ = graph.grounding_candidates(state)
    return [c["kb_entry_id"] for c in usable]


@pytest.fixture()
def kb():
    kb_fixture.load()


# ---------------------------------------------------------------------------
# Nothing to do named: one question, then the KB or a ticket
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("message, verb", [
    ("How do I add it", "do"),
    ("I want to add a new one", "do"),
    ("how do I set it up", "set up"),
    ("how to configure", "set up"),
])
def test_a_how_to_with_no_subject_gets_one_question_and_no_ticket(client, message, verb):
    headers = _customer(client)
    chat = _chat(client, headers, message)
    assert chat["status"] == "active" and not chat.get("ticket_id")
    assert _ai_lines(chat) == [graph.HOW_TO_SUBJECT_QUESTION.format(verb=verb, product="Brightdesk HR",
                                                                    options=MODULES)]
    assert "answer" not in client.model.ops()  # fixed text, no model call
    question = _ai_lines(chat)[0].lower()
    for module in ("attendance", "expenses", "leave", "payroll"):
        assert module in question
    assert "android" not in question  # a platform, not a part of the product
    assert "name" not in question and "account" not in question and "id" not in question.split()


def test_without_modules_the_question_is_open(client):
    kb_fixture.topic_terms.use([])
    headers = _customer(client)
    chat = _chat(client, headers, "How do I add it")
    assert _ai_lines(chat) == ["What exactly do you want to do in Brightdesk HR?"]


def test_the_answer_to_the_question_is_answered_from_the_kb(client):
    headers = _customer(client)
    chat = _chat(client, headers, "How do I add it")
    chat = _send(client, headers, chat, "an expense claim")
    assert chat["status"] == "active"
    assert _ai_lines(chat) == [TYPE_QUESTION, ANSWER]
    assert "New Claim" in client.model.answered_from()
    assert _ai_lines(chat).count(TYPE_QUESTION) == 1


def test_no_guide_after_the_question_raises_a_ticket(client):
    headers = _customer(client)
    chat = _chat(client, headers, "How do I add it")
    chat = _send(client, headers, chat, "a performance review cycle")
    assert chat["status"] == "escalated" and chat["ticket_id"]
    lines = _ai_lines(chat)
    assert lines[0] == TYPE_QUESTION and lines[1] == graph.NO_KB_REPLY_CHAT
    assert chat["ticket_id"] in lines[2]
    assert "answer" not in client.model.ops()  # no improvised steps


def test_not_sure_after_the_question_raises_a_ticket_never_a_second_question(client):
    # "not" carries the negation tag, whose hand-off wins (routing policy).
    headers = _customer(client)
    chat = _chat(client, headers, "How do I add it")
    chat = _send(client, headers, chat, "not sure")
    assert chat["status"] == "escalated" and chat["ticket_id"]
    lines = _ai_lines(chat)
    assert lines[0] == TYPE_QUESTION and len(lines) == 2 and chat["ticket_id"] in lines[1]
    assert "answer" not in client.model.ops()


# ---------------------------------------------------------------------------
# Subject clear: the KB entry about that task, extra words or not
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("question, entry", [
    ("how do I apply for a vacation day next week", "KB-0001"),
    ("how can I export the attendance report for last month as excel", "KB-0006"),
    ("how to submit an expense claim for my taxi ride", "KB-0008"),
    ("how do I connect brightdesk to our slack workspace", "KB-0007"),
    ("I need to install the app on my iphone", "KB-0003"),
])
def test_natural_wording_finds_the_how_to_entry(kb, question, entry):
    assert _usable(question)[:1] == [entry]


@pytest.mark.parametrize("question, not_this", [
    ("how do I set up an overtime report for leave approvals", "KB-0001"),  # shares only "leave"
    ("how do I add a dashboard widget for attendance", "KB-0006"),
])
def test_a_one_word_overlap_on_something_else_does_not_count(kb, question, not_this):
    assert not_this not in _usable(question)


def test_a_troubleshooting_entry_never_answers_a_how_to(kb):
    assert "KB-0009" not in _usable("how do I set up clock-in on the app")


def test_a_clear_how_to_is_answered_from_its_entry(client):
    headers = _customer(client)
    chat = _chat(client, headers, "how do I connect brightdesk to our slack workspace")
    assert chat["status"] == "active"
    assert _ai_lines(chat) == [ANSWER]
    prompt = client.model.answered_from()
    assert "slack workspace" in prompt
    # The guide settles the subject: the model isn't told the product area is missing.
    assert "covered by the kb_guidance guide" in prompt and "not stated yet" not in prompt


def test_a_clear_how_to_with_no_entry_gets_the_friendly_reply_and_a_ticket(client):
    headers = _customer(client)
    chat = _chat(client, headers, "how do I add a performance review cycle")
    assert chat["status"] == "escalated"
    lines = _ai_lines(chat)
    assert lines[0] == graph.NO_KB_REPLY_CHAT and chat["ticket_id"] in lines[1]
    assert "guess" not in lines[0] and "answer" not in client.model.ops()


# ---------------------------------------------------------------------------
# Guides for one platform each
# ---------------------------------------------------------------------------
def test_platform_guides_ask_which_platform_first(client):
    headers = _customer(client)
    chat = _chat(client, headers, "how do I install the mobile app")
    assert chat["status"] == "active"
    assert _ai_lines(chat) == [graph.HOW_TO_VARIANT_QUESTION.format(options="Android or iOS")]
    assert "answer" not in client.model.ops()
    chat = _send(client, headers, chat, "iOS")
    assert chat["status"] == "active" and _ai_lines(chat)[1] == ANSWER
    transcript = (f"Customer: how do I install the mobile app\nAgent (AI): {_ai_lines(chat)[0]}\n"
                  "Customer: iOS")
    state = {"ticket_text": transcript}
    state.update(graph.retrieve_kb_candidates(state))
    assert graph.grounding_candidates(state)[0][0]["kb_entry_id"] == "KB-0003"
    assert graph.how_to_question(state) is None  # never asked twice


def test_naming_the_platform_up_front_skips_the_question(kb):
    assert _usable("how do I install the app on my ipad")[:1] == ["KB-0003"]
    state = {"ticket_text": "Customer: how do I install the app on my ipad"}
    state.update(graph.retrieve_kb_candidates(state))
    assert graph.how_to_question(state) is None


# ---------------------------------------------------------------------------
# Routing order and the ticket form
# ---------------------------------------------------------------------------
def test_escalation_language_still_wins_over_the_how_to_question():
    state = {"ticket_text": "Customer: how do I add it, this is useless garbage",
             "confidence": 0.9, "category": "ISSUE",
             "language_tags": ["offensive_language"], "clarification_attempts": 0}
    assert graph.decide_route(state)["route"] == "human"


def test_the_question_is_never_asked_twice(kb):
    text = f"Customer: How do I add it\nAgent (AI): {TYPE_QUESTION}\nCustomer: something else"
    state = {"ticket_text": text, "confidence": 0.9, "category": "ISSUE", "clarification_attempts": 1}
    assert graph.asked_how_to_question(text) and graph.how_to_question(state) is None
    assert graph.decide_route(state)["route"] == "ai"


def test_the_ticket_form_asks_by_email_then_answers(client):
    headers = _customer(client)
    res = client.post("/api/tickets", json={"subject": "Question", "description": "How do I add it",
                                            "priority": "medium"}, headers=headers)
    assert res.status_code == 200, res.text
    ticket_id = res.json()["ticket_id"]
    thread = client.get(f"/api/tickets/{ticket_id}", headers=headers).json()
    ai = [m["message"] for m in thread["messages"] if m["sender"] == "ai"]
    assert len(ai) == 1 and ai[0].startswith("Hi Dana,") and TYPE_QUESTION in ai[0]
    assert thread["ticket"]["status"] == "pending_customer"
    res = client.post(f"/api/tickets/{ticket_id}/reply", json={"message": "an expense claim"}, headers=headers)
    assert res.status_code == 200, res.text
    thread = client.get(f"/api/tickets/{ticket_id}", headers=headers).json()
    ai = [m["message"] for m in thread["messages"] if m["sender"] == "ai"]
    assert len(ai) == 2 and ANSWER in ai[1]
    assert "answer" in client.model.ops()
