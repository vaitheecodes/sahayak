"""Vague messages, latest-message-first retrieval, and the repeat guard.

- "I have an issue" (or one naming only the product) describes no
  symptom: no KB grounding, one open question, no model call.
- The KB search uses the customer's latest message first; earlier
  messages only add context when the latest is short or vague. A clear
  new question is grounded on its own topic.
- A reply (near-)identical to one of the AI's last two replies is
  regenerated once, then replaced by a different useful question or a
  ticket offer: the same reply is never sent twice in a row.
- The answer prompt says to answer a clear question in the latest
  message first.

On the neutral test KB (tests/kb_fixture.py, the fictional Brightdesk HR).
"""

from __future__ import annotations

import pytest

from backend import graph
from backend.ai_service import chat_response, provider
from backend.ai_service.schemas import AnswerInput, ClarifyInput
from tests import kb_fixture

OPEN_PAYROLL = chat_response.open_question("Payroll")
EXPENSE_QUESTION = "How do I submit an expense claim with a receipt"


def _t(*messages, ai="Can you tell me more?"):
    return "\n".join(f"Customer: {m}\nAgent (AI): {ai}" for m in messages[:-1]) + (
        "\n" if len(messages) > 1 else "") + f"Customer: {messages[-1]}"


@pytest.fixture(autouse=True)
def _kb():
    kb_fixture.load()


# ---------------------------------------------------------------------------
# Vague messages
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text, vague", [
    ("I have an issue", True),
    ("help", True),
    ("Hi, I am facing a problem with Brightdesk", True),
    ("it is not working", True),
    ("I am facing issue in adding an expense", False),
    ("my payslip is missing", False),
    (EXPENSE_QUESTION, False),
])
def test_vague_detection(text, vague):
    assert graph.is_vague(f"Customer: {text}") is vague


def test_earlier_detail_makes_a_later_vague_message_not_vague():
    assert graph.is_vague(_t("my payslip is missing", "help")) is False


def test_open_question_names_the_product_area():
    assert OPEN_PAYROLL == ("What are you seeing, or trying to do, in Payroll? For example: something "
                            "missing or wrong, an error on the screen, a setting, or a task you want to do.")
    assert "trying to do, in Brightdesk HR?" in chat_response.open_question(None)


@pytest.mark.parametrize("node", ["generate_response", "ask_clarifying_question"])
def test_a_vague_message_gets_one_open_question_without_grounding(node):
    """conftest disables the provider: any model call would raise."""
    state = {"ticket_text": "Customer: I have an issue with payroll", "reply_format": "chat"}
    assert graph.is_vague(state["ticket_text"]) is False
    state = {"ticket_text": "Customer: I have an issue with Brightdesk", "reply_format": "chat",
             "kb_candidates": [kb_fixture.candidate("KB-0002")]}  # a generic match...
    assert getattr(graph, node)(state)["ai_response"] == chat_response.open_question(None)  # ...not used


def test_reply_context_for_a_vague_message():
    state = {"ticket_text": "Customer: I have an issue", "kb_candidates": [kb_fixture.candidate("KB-0004")]}
    ctx = graph._reply_context(state)
    assert ctx["vague"] is True and ctx["kb_candidates"] == [] and ctx["unconfirmed_topics"] == []
    assert ctx["subject"] is None and ctx["subject_known"] is False


# ---------------------------------------------------------------------------
# Retrieval query: latest message first
# ---------------------------------------------------------------------------
def test_a_clear_latest_question_is_searched_on_its_own():
    transcript = _t("I have an issue", EXPENSE_QUESTION)
    assert graph.retrieval_query(transcript) == EXPENSE_QUESTION
    state = {"ticket_text": transcript}
    state.update(graph.retrieve_kb_candidates(state))
    assert state["kb_candidates"][0]["kb_entry_id"] == "KB-0008"


def test_a_clear_new_question_is_not_pulled_back_to_an_older_topic():
    transcript = _t("how do I install the app on android", EXPENSE_QUESTION)
    state = {"ticket_text": transcript}
    state.update(graph.retrieve_kb_candidates(state))
    assert state["kb_candidates"][0]["kb_entry_id"] == "KB-0008"


def test_a_short_latest_message_borrows_earlier_context():
    transcript = _t("my payslip is missing this month", "still the same")
    query = graph.retrieval_query(transcript)
    assert query.splitlines() == ["still the same", "still the same", "my payslip is missing this month"]
    assert graph.kb_candidates_for(query)  # the earlier message carries the topic


def test_retrieval_query_never_contains_the_ai_reply():
    transcript = _t("my payslip is missing", "ok", ai="Install the Brightdesk app from Google Play.")
    assert "Google" not in graph.retrieval_query(transcript)


def test_customer_messages_are_split_per_message():
    transcript = "Customer: first line\nsecond line\nAgent (AI): reply\n1. step\nCustomer: next"
    assert graph._customer_messages(transcript) == ["first line\nsecond line", "next"]
    assert graph._customer_messages("plain ticket text") == ["plain ticket text"]


# ---------------------------------------------------------------------------
# Repeat guard
# ---------------------------------------------------------------------------
PREVIOUS = "Can you please provide the exact error message you're seeing when you try to submit the expense claim?"


@pytest.mark.parametrize("text, expected", [
    (PREVIOUS, True),
    (PREVIOUS.replace("please ", ""), True),
    ("Could you please provide the exact error message you're seeing when you try to submit the expense claim?",
     True),
    ("Can you provide the exact error message you see when submitting the expense claim?", False),  # < 80%
    ("To claim an expense, open Expenses and click New Claim.", False),
])
def test_repeat_detection(text, expected):
    assert chat_response.repeats(text, ["Something else entirely.", PREVIOUS]) is expected


def _scripted(monkeypatch, *replies):
    calls = []
    queue = list(replies)

    def fake(instructions, data, **kwargs):
        calls.append((instructions, data))
        return queue.pop(0)

    monkeypatch.setattr(provider, "complete_text", fake)
    return calls


def _answer(**fields):
    return chat_response.answer(AnswerInput(
        ticket_text=_t("I have an issue with adding an expense", EXPENSE_QUESTION),
        latest_message=EXPENSE_QUESTION, **fields))


def test_a_repeat_is_regenerated_with_an_instruction_to_move_on(monkeypatch):
    calls = _scripted(monkeypatch, PREVIOUS, "Open Expenses, click New Claim and attach the receipt.")
    log = provider.start_failure_log()
    reply = _answer(recent_ai_replies=[PREVIOUS])
    assert reply.text == "Open Expenses, click New Claim and attach the receipt."
    assert len(calls) == 2
    instructions, data = calls[1]
    assert "repeated one of your previous replies" in instructions
    assert data["your_previous_replies"] == PREVIOUS
    assert [(f.code, f.outcome) for f in log] == [("repeated_reply", "regenerated")]


def test_a_second_repeat_falls_back_to_a_different_question(monkeypatch):
    _scripted(monkeypatch, PREVIOUS, PREVIOUS)
    log = provider.start_failure_log()
    reply = _answer(recent_ai_replies=[PREVIOUS], subject_known=True)
    assert reply.text == chat_response.DETAIL_QUESTION
    assert not chat_response.repeats(reply.text, [PREVIOUS])
    assert [f.outcome for f in log] == ["regenerated", "fallback"]


def test_fallback_skips_questions_that_were_already_asked(monkeypatch):
    _scripted(monkeypatch, PREVIOUS, PREVIOUS)
    recent = [chat_response.DETAIL_QUESTION, PREVIOUS]
    assert _answer(recent_ai_replies=recent).text == chat_response.TRIED_QUESTION
    _scripted(monkeypatch, PREVIOUS, PREVIOUS)
    recent = [chat_response.TRIED_QUESTION, PREVIOUS, chat_response.DETAIL_QUESTION]
    assert _answer(recent_ai_replies=recent).text == chat_response.OFFER_TICKET_CHAT


def test_a_vague_open_question_is_not_repeated(monkeypatch):
    data = ClarifyInput(ticket_text="Customer: hi", vague=True, subject="Payroll",
                        recent_ai_replies=[OPEN_PAYROLL])
    reply = chat_response.clarify(data)
    assert reply.text != OPEN_PAYROLL and reply.text == chat_response.DETAIL_QUESTION


def test_no_repeat_check_without_previous_replies(monkeypatch):
    calls = _scripted(monkeypatch, PREVIOUS)
    assert _answer().text == PREVIOUS and len(calls) == 1


def test_recent_replies_reach_the_prompt_input(monkeypatch):
    seen = {}
    monkeypatch.setattr(chat_response, "answer", lambda d: seen.setdefault("d", d) and chat_response.ChatReply(text="x"))
    state = {"ticket_text": _t("my payslip is missing", "on Android"), "recent_ai_replies": ["a", "b", "c"]}
    state.update(graph.retrieve_kb_candidates(state))
    graph.generate_response(state)
    assert seen["d"].recent_ai_replies == ["b", "c"] and seen["d"].latest_message == "on Android"


# ---------------------------------------------------------------------------
# Answer the latest clear question first
# ---------------------------------------------------------------------------
def test_answer_prompt_answers_the_latest_question_first(monkeypatch):
    calls = _scripted(monkeypatch, "Open Expenses and click New Claim.")
    _answer()
    instructions, data = calls[0]
    assert "latest message (the customer_latest_message block)" in instructions
    assert "answer that question first" in instructions
    assert data["customer_latest_message"] == EXPENSE_QUESTION
