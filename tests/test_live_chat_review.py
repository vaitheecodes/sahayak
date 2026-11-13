"""Three kinds of live chat found in a deployment review, replayed locally
on the neutral test KB (tests/kb_fixture.py, the fictional Brightdesk HR).

A. A vague report on a high-risk topic ("my dashboard looks different
   after changing our plan", ACCOUNT below the stricter bar): one
   clarifying question first (where they sign in, what is on the screen),
   never KB topics or causes; the next turn raises the ticket. The hand-off
   has no "N/A", "Already tried: Nothing stated yet", no finding that
   restates the issue, and "No KB match - needs triage" instead of
   invented steps.
B. A how-to the KB doesn't cover: an honest "no guide" reply and a ticket,
   no improvised steps; troubleshooting entries never answer a how-to. A
   how-to that the KB does cover keeps only the steps the KB entry
   supports, with no "if you encounter issues, provide the exact error
   message" line.
C. Another uncovered how-to with an unsure classifier: no "are you
   referring to...?" (a how-to is clear), no "exact error message" (none
   was reported), the honest reply and a ticket, in chat and by email.

Everything is real (FastAPI app, LangGraph pipeline, KB retrieval, SQLite)
except the language model: provider.complete is a scripted fake.
"""

from __future__ import annotations

import itertools
import json

import pytest
from fastapi.testclient import TestClient

from backend import chats, conversation, db, graph, main, request_kind, runtime
from backend.ai_service import chat_response, grounding, provider
from backend.ai_service.schemas import AnswerInput, ClarifyInput, HandoffSummary, KBCandidate
from backend.ai_service.summarize_conversation import NOTHING_TRIED, tidy_handoff
from tests import kb_fixture

_counter = itertools.count()

A1 = "My dashboard looks different after changing our plan"
A_QUESTION = "Where do you sign in, the website or the mobile app, and what appears on the screen?"
A2 = "On the website. After I sign in the dashboard is empty."
B = "I need to set up a performance review cycle, how to do?"
C = "I need to add a biometric device"


class _Model:
    """Answers by operation, recognised from the trusted instructions."""

    def __init__(self, category="ISSUE", confidence=0.9):
        self.category, self.confidence = category, confidence
        self.calls: list[tuple[str, str, str]] = []  # (operation, system, user)
        self.answer = "Unused."
        self.handoff = {"issue": "Unused.", "tried": [], "findings": [], "unresolved_questions": []}

    def __call__(self, messages, **kwargs):
        system, user = messages[0]["content"], messages[1]["content"]

        def note(op):
            self.calls.append((op, system, user))

        if "You classify support tickets" in system:
            note("categorize")
            return json.dumps({"category": self.category, "confidence": self.confidence})
        if "reported a problem about their account, licensing" in system:
            note("clarify_high_risk")
            return A_QUESTION
        if "too ambiguous to classify confidently" in system:
            note("clarify")
            return "Are you referring to installing the mobile app?"
        if "Rewrite the guidance in the kb_guidance block" in system:
            note("info_request")
            return "1. Open Settings > Data Export.\n2. Choose the date range and export."
        if "support assistant for Brightdesk HR" in system or "helpful customer support agent" in system:
            note("answer")
            return self.answer
        if "Decide whether the customer's new message is a CONTINUATION" in system:
            note("continuation")
            return json.dumps({"is_continuation": False})
        if "taking over" in system:
            note("handoff_summary")
            return json.dumps(self.handoff)
        if "Suggest 2-5 concrete next steps" in system:
            note("suggest_steps")
            return json.dumps({"steps": ["Review the plan's licence usage.",
                                         "Confirm the browser can reach app.example.com on 443."]})
        raise AssertionError(f"Unexpected AI operation: {system[:80]}")

    def ops(self) -> list[str]:
        return [op for op, _, _ in self.calls]

    def system_for(self, op: str) -> str:
        return next(system for name, system, _ in self.calls if name == op)


@pytest.fixture(autouse=True)
def _kb():
    kb_fixture.load()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    model = _Model()
    monkeypatch.setattr(provider, "complete", model)
    with TestClient(main.app) as c:
        kb_fixture.load()  # after startup, which reloads the settings
        runtime.set_graph(graph.build_graph())  # the real routing pipeline
        c.model = model
        yield c


def _customer(client):
    res = client.post("/api/auth/customer/signup", json={
        "name": "Dana Smith", "email": f"review-{next(_counter)}@example.com", "password": "password123"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _chat(client, headers, issue):
    res = client.post("/api/chats", json={"issue": issue}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _send(client, headers, session_id, message):
    res = client.post(f"/api/chats/{session_id}/messages", json={"message": message}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _ticket(ticket_id):
    conn = db.get_connection()
    try:
        return dict(conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone())
    finally:
        conn.close()


def _ai_lines(chat):
    return [m["content"] for m in chat["messages"] if m["role"] == "ai"]


# ---------------------------------------------------------------------------
# A: a vague report on a high-risk topic
# ---------------------------------------------------------------------------
def test_a_vague_account_report_gets_one_question_then_a_ticket(client):
    model = client.model
    model.category, model.confidence = "ACCOUNT", 0.81
    model.handoff = {  # what a model may write, plus one real new fact
        "issue": "The dashboard looks different after changing the plan.",
        "tried": ["N/A"],
        "findings": ["The dashboard looks different after changing the plan.",
                     "After signing in on the website the dashboard is empty."],
        "unresolved_questions": ["N/A", "What exactly was changed on the plan?"],
    }
    headers = _customer(client)

    # Turn 1: one question about what is unclear, no ticket yet.
    chat = _chat(client, headers, A1)
    assert chat["status"] == "active" and chat["ticket_id"] is None
    assert _ai_lines(chat) == [A_QUESTION]
    system = model.system_for("clarify_high_risk")
    assert "for example the website or a mobile app" in system and "Brightdesk HR" in system
    clarify_call = json.dumps([c for c in model.calls if c[0] == "clarify_high_risk"])
    assert "KB-0010" not in clarify_call and "Change the subscription plan" not in clarify_call
    assert "answer" not in model.ops() and "clarify" not in model.ops()

    # Turn 2: still ACCOUNT below the bar -> the ticket, no second question.
    chat = _send(client, headers, chat["session_id"], A2)
    assert chat["status"] == "escalated" and model.ops().count("clarify_high_risk") == 1
    ticket = _ticket(chat["ticket_id"])
    brief = json.loads(ticket["ai_summary"])
    assert brief["tried"] == [NOTHING_TRIED]
    assert brief["findings"] == ["After signing in on the website the dashboard is empty."]
    assert brief["unresolved_questions"] == ["What exactly was changed on the plan?"]
    assert json.loads(ticket["ai_suggestions"]) == [conversation.NO_KB_STEPS]
    assert "suggest_steps" not in model.ops()
    for invented in ("app.example.com", "443", "licence usage", "N/A"):
        assert invented not in ticket["ticket_text"]
    assert "Already tried:\n- Nothing stated yet" in ticket["ticket_text"]
    # The summary prompt asks for real unknowns, not placeholders.
    summary_prompt = model.system_for("handoff_summary")
    assert "never 'N/A'" in summary_prompt and "which login" in summary_prompt


def test_a_reported_error_on_a_high_risk_topic_goes_straight_to_a_human():
    state = {"ticket_text": "Customer: The data export fails with error 'quota exceeded'",
             "category": "DATA", "confidence": 0.81, "clarification_attempts": 0, "language_tags": []}
    state.update(graph.retrieve_kb_candidates(state))
    assert graph.decide_route(state)["route"] == "human"


def test_a_high_risk_escalate_with_info_entry_gives_its_steps_collect_list_and_note(monkeypatch):
    entry = {"kb_entry_id": "KB-0900", "category": "DATA", "intent": "Request a data export",
             "instruction": "How do I export my account data", "score": 0.6,
             "response": "Open Settings > Data Export.\nChoose the date range and export.",
             "handling": "escalate_with_info", "collect": ["Account owner email", "Date range needed"]}
    state = {"ticket_text": "Customer: I need my account data exported", "category": "DATA",
             "confidence": 0.6, "clarification_attempts": 0, "language_tags": [], "kb_candidates": [entry]}
    route = graph.decide_route(state)
    assert route["route"] == "ai" and "escalate_with_info" in route["route_reason"]

    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: (
        "1. Open Settings > Data Export.\n2. Choose the date range and export."))
    reply = graph.generate_response({**state, "reply_format": "chat"})
    assert reply["needs_info"]["kb_entry_id"] == "KB-0900"
    assert graph.handoff_reason(reply["needs_info"]) == "kb_needs_info"
    text = reply["ai_response"]
    assert "1. Open Settings > Data Export." in text and "2. Choose the date range" in text
    assert "Please add these to your ticket:\n- Account owner email\n- Date range needed" in text
    assert text.endswith(chat_response.INFO_SAFETY_NOTE)


# ---------------------------------------------------------------------------
# B: how-to requests
# ---------------------------------------------------------------------------
def test_b_a_how_to_with_no_kb_entry_says_so_and_raises_a_ticket(client):
    model = client.model
    model.category, model.confidence = "SETUP", 0.9
    model.handoff = {"issue": "The customer wants to set up a performance review cycle.", "tried": [],
                     "findings": [], "unresolved_questions": ["Which teams take part in the review?"]}
    headers = _customer(client)
    chat = _chat(client, headers, B)
    assert chat["status"] == "escalated"
    (first,) = _ai_lines(chat)   # "no guide" and the ticket number: one message
    assert first.startswith(chats.NO_GUIDE_LEAD) and chat["ticket_id"] in first
    assert "answer" not in model.ops()  # no improvised steps
    ticket = _ticket(chat["ticket_id"])
    assert json.loads(ticket["ai_suggestions"]) == [conversation.NO_KB_STEPS]
    reason = next(user for op, _, user in model.calls if op == "handoff_summary")
    assert "No knowledge-base article covers this request" in reason


def test_b_troubleshooting_entries_never_ground_a_how_to():
    question = "I need to set up clock-in, how to do?"
    assert request_kind.is_how_to(question)
    state = {"ticket_text": f"Customer: {question}"}
    state.update(graph.retrieve_kb_candidates(state))
    usable, _ = graph.grounding_candidates(state)
    assert not any(c["kb_entry_id"] == "KB-0009" for c in usable)  # clock-in *fails*
    assert usable == []


def test_b_a_covered_how_to_keeps_only_kb_steps_and_no_error_boilerplate(client):
    model = client.model
    model.category, model.confidence = "USAGE", 0.9
    model.answer = (
        "1. Open Attendance, then Reports.\n"
        "2. Go to Settings > Payroll > Export and click Run.\n"
        "3. Pick the date range and click Export.\n"
        "If you encounter issues, please provide the exact error message.")
    headers = _customer(client)
    chat = _chat(client, headers, "how do I export the attendance report")
    assert chat["status"] == "active"
    (reply,) = _ai_lines(chat)
    # The invented middle step can't be dropped from a procedure without leaving it
    # incomplete: regenerated, then the guide's own answer and steps.
    assert reply == ("Attendance reports can be exported as CSV or Excel from the Reports page.\n"
                     "1. Open Attendance, then Reports.\n2. Pick the date range and click Export.")
    system = model.system_for("answer")
    assert "how-to request" in system and "exact error text" not in system


# ---------------------------------------------------------------------------
# C: an uncovered how-to with an unsure classifier
# ---------------------------------------------------------------------------
def test_c_a_how_to_is_not_clarified_and_gets_an_honest_ticket(client):
    model = client.model
    model.category, model.confidence = "SETUP", 0.4  # the model was unsure
    model.handoff = {"issue": "The customer wants to add a biometric device.", "tried": [],
                     "findings": [], "unresolved_questions": ["Which device model is it?"]}
    headers = _customer(client)
    chat = _chat(client, headers, C)
    assert chat["status"] == "escalated"
    text = json.dumps(_ai_lines(chat))
    assert "referring to" not in text and "error message" not in text
    assert _ai_lines(chat)[0].startswith(chats.NO_GUIDE_LEAD)
    assert "clarify" not in model.ops() and "answer" not in model.ops()
    assert json.loads(_ticket(chat["ticket_id"])["ai_suggestions"]) == [conversation.NO_KB_STEPS]


def test_c_the_ticket_path_gives_the_same_honest_reply(client):
    client.model.category, client.model.confidence = "SETUP", 0.4
    client.model.handoff = {"issue": "Add a biometric device.", "tried": [], "findings": [],
                            "unresolved_questions": []}
    headers = _customer(client)
    res = client.post("/api/tickets", json={"subject": "Biometric device", "description": C, "priority": "medium"},
                      headers=headers)
    assert res.status_code == 200, res.text
    ticket = _ticket(res.json()["ticket_id"])
    assert ticket["route"] == "human" and ticket["status"] == "open"
    thread = client.get(f"/api/tickets/{ticket['ticket_id']}", headers=headers).json()["messages"]
    assert any(graph.NO_KB_REPLY_EMAIL in m["message"] for m in thread if m["sender"] == "ai")
    assert json.loads(ticket["ai_suggestions"]) == [conversation.NO_KB_STEPS]


# ---------------------------------------------------------------------------
# The filters on their own
# ---------------------------------------------------------------------------
def test_error_message_is_asked_for_only_after_an_error_was_reported():
    reply = "1. Open Leave.\nIf you see anything odd, what is the exact error message?"
    assert "error" not in chat_response.clean_chat_reply(reply, error_reported=False)
    assert "exact error message" in chat_response.clean_chat_reply(reply, error_reported=True)
    assert chat_response.detail_question(True, False) == chat_response.STEP_QUESTION
    assert chat_response.detail_question(True, True) == chat_response.DETAIL_QUESTION
    assert chat_response.detail_question(False, True) == chat_response.subject_question()
    assert not graph.error_reported(f"Customer: {C}\nAgent (AI): ok\nCustomer: yes")
    assert graph.error_reported("Customer: submitting the claim fails with error 401")


@pytest.mark.parametrize("text, how_to", [
    (B, True), (C, True), ("how do I export the attendance report", True), ("apply for leave", True),
    (A1, False), ("my payslip is missing", False), ("submitting the claim fails", False),
    ("what is the data retention period", False),
])
def test_how_to_detection(text, how_to):
    assert request_kind.is_how_to(text) is how_to


def test_how_to_boilerplate_is_dropped_only_for_how_to():
    reply = "Use the New Claim form.\nIf you encounter issues, let me know."
    assert chat_response.clean_chat_reply(reply, how_to=True) == "Use the New Claim form."
    assert "encounter" in chat_response.clean_chat_reply(reply, how_to=False)


@pytest.mark.parametrize("step, ok", [
    ("Open Attendance and select Reports.", True),
    ("Go to Settings > Payroll > Export and click Run.", False),      # path not in the KB
    ("Confirm the browser can reach app.example.com on 443.", False),  # host and port not in the KB
    ("Each report can hold up to 500 rows a day.", False),             # number not in the KB
    ("Reinstall the app and clear the cache.", False),
])
def test_steps_must_be_supported_by_the_kb_entry(step, ok):
    kb = "To export the attendance report, open Attendance, select Reports, pick the date range and click Export."
    assert grounding.supported(step, kb) is ok


def test_menu_paths_from_the_kb_are_kept():
    kb = "Make sure the approver is set under Settings > Leave Policies."
    assert grounding.supported("Go to Settings > Leave Policies and set the approver.", kb)


def test_an_answer_with_only_invented_steps_is_regenerated_not_sent(monkeypatch):
    replies = iter(["1. Go to Settings > Payroll > Export.\n2. Click Run.",
                    "Attendance reports are exported from the Reports page."])
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: next(replies))
    kb = KBCandidate(**kb_fixture.candidate("KB-0006", score=1.0))
    data = AnswerInput(ticket_text="Customer: how do I export the attendance report", kb_candidates=[kb],
                       how_to=True, error_reported=False, latest_message="how do I export the attendance report")
    assert chat_response.answer(data).text == "Attendance reports are exported from the Reports page."


def test_handoff_tidy_drops_placeholders_and_restatements():
    summary = HandoffSummary(
        issue="My dashboard looks different after changing the plan.",
        tried=["N/A"], findings=["The dashboard looks different after changing our plan", "none"],
        unresolved_questions=["N/A", "Where do you sign in: website or mobile app?"])
    tidy = tidy_handoff(summary, A1)
    assert tidy.tried == [NOTHING_TRIED] and tidy.findings == []
    assert tidy.unresolved_questions == ["Where do you sign in: website or mobile app?"]
    assert "Findings" not in tidy.as_text([conversation.NO_KB_STEPS])


def test_handoff_steps_come_only_from_a_matching_kb_entry():
    assert graph.handoff_kb_candidates(A1) == []  # "plan" alone is no match
    hits = graph.handoff_kb_candidates("how do I export the attendance report")
    assert [c["kb_entry_id"] for c in hits][:1] == ["KB-0006"]


def test_high_risk_clarify_gets_no_kb_topics_or_product_area_question(monkeypatch):
    seen = {}

    def fake(instructions, blocks, operation="", **kwargs):
        seen.update(instructions=instructions, blocks=blocks)
        return A_QUESTION

    monkeypatch.setattr(provider, "complete_text", fake)
    state = {"ticket_text": f"Customer: {A1}", "category": "ACCOUNT", "confidence": 0.81, "reply_format": "chat"}
    state.update(graph.retrieve_kb_candidates(state))
    assert graph.ask_clarifying_question(state)["ai_response"] == A_QUESTION
    assert "candidate_topics" not in seen["blocks"]
    assert chat_response._SUBJECT_FIRST not in seen["instructions"]
    assert ClarifyInput(ticket_text="x").high_risk is False
