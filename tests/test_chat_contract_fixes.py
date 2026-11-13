"""Fixes the real-model chat eval found (docs/CHAT_CONTRACT.md), pinned
with scripted replies: no model calls."""

from __future__ import annotations

from backend.ai_service import chat_response, provider
from backend.ai_service.schemas import AnswerInput, ClarifyInput, KBCandidate

ENTRY = KBCandidate(kb_entry_id="KB-1", category="SETUP", intent="Allow the widget", score=0.8,
                    instruction="How do I allow the widget?", response="Allow the widget's servers in your policy.")


def test_not_covered_with_more_text_after_it_never_reaches_the_customer():
    data = AnswerInput(ticket_text="Customer: my script fails", kb_candidates=[ENTRY], customer_text="my script fails")
    reply = chat_response._frame("NOT_COVERED  Please specify which part of the product this is about.", data)
    assert reply.not_covered and reply.text == chat_response.NOT_COVERED


def test_with_kb_topics_the_question_names_them_not_which_part_of_the_product(monkeypatch):
    prompts = []
    monkeypatch.setattr(provider, "complete_text", lambda instructions, *a, **k: prompts.append(instructions) or
                        "Is this about allowing the widget in your policy?")
    chat_response.clarify(ClarifyInput(ticket_text="Customer: connection trouble", category="SETUP", confidence=0.5,
                                       kb_candidates=[ENTRY], subject_known=False))
    assert chat_response._SUBJECT_FIRST not in prompts[0]


def test_a_how_to_fallback_never_asks_troubleshooting_questions(monkeypatch):
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: "[Your answer here]")   # rejected every time
    reply = chat_response.clarify(ClarifyInput(ticket_text="Customer: how do I add a holiday", category="USAGE",
                                               confidence=0.5, how_to=True, subject_known=True))
    assert reply.text not in (chat_response.STEP_QUESTION, chat_response.TRIED_QUESTION,
                              chat_response.DETAIL_QUESTION)


def test_an_answer_turn_that_is_only_a_question_becomes_the_guides_answer(monkeypatch):
    # Chat eval rule 5: on answer turns the model asked one question after another.
    monkeypatch.setattr(provider, "complete_text",
                        lambda *a, **k: "Have you checked if the widget's servers are in your policy?")
    data = AnswerInput(ticket_text="Customer: my widget is blocked", kb_candidates=[ENTRY],
                       customer_text="my widget is blocked")
    assert chat_response.answer(data).text == ENTRY.response
    assert chat_response.only_a_question("Is it the Leave page or Payroll?")
    assert not chat_response.only_a_question("Allow the servers. 1. Open the policy. Done?")
