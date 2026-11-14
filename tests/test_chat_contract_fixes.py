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


def test_what_are_the_sources_names_the_guide_and_its_page_without_a_model(monkeypatch):
    from backend import graph

    entry = ENTRY.model_copy(update={"source_url": "https://help.example.com/widget"})
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model")))
    state = {"ticket_text": "Customer: allow the widget?\nAgent (AI): Allow the servers.\nCustomer: what are the sources?",
             "kb_candidates": [entry.model_dump() | {"kb_entry_id": "KB-1"}], "recent_ai_replies": ["Allow the servers."], "answered": True,
             "reply_format": "chat"}
    reply = graph.generate_response(state)["ai_response"]
    assert reply == 'This comes from our guide "Allow the widget": https://help.example.com/widget.'


def test_a_follow_up_the_guide_doesnt_answer_gets_the_ticket_offer(monkeypatch):
    from backend import graph

    monkeypatch.setattr(chat_response, "covers_latest", lambda data: False)
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no answer")))
    state = {"ticket_text": "Customer: allow the widget?\nAgent (AI): Allow the servers.\n"
                            "Customer: will my manager get a notification?",
             "kb_candidates": [ENTRY.model_dump()], "recent_ai_replies": ["Allow the servers."], "answered": True, "reply_format": "chat"}
    result = graph.generate_response(state)
    assert result["ai_response"] == chat_response.FOLLOWUP_NOT_COVERED and result["needs_info"] is None
    from backend import handoff_signals
    assert handoff_signals.is_escalation_acceptance("yes", chat_response.FOLLOWUP_NOT_COVERED)


def test_a_reply_that_copies_a_prompt_block_is_regenerated(monkeypatch):
    # Chat eval: an info request showed "<kb_guidance> [ACCOUNT / ...] (match score 0.50)".
    replies = iter(["<kb_guidance>\n[SETUP / Allow the widget] (match score 0.80)\n</kb_guidance>",
                    "Allow the widget's servers in your policy."])
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: next(replies))
    data = AnswerInput(ticket_text="Customer: allow the widget?", kb_candidates=[ENTRY], customer_text="allow the widget?")
    assert chat_response.answer(data).text == "Allow the widget's servers in your policy."


def test_an_info_request_never_shows_invented_steps_or_its_prompt(monkeypatch):
    entry = ENTRY.model_copy(update={"handling": "escalate_with_info", "collect": ["a screenshot"],
                                     "response": "Open the policy page. Allow the widget's servers."})
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k:
                        "1. Click your profile icon in the top right corner.\n2. Allow the widget's servers.")
    text = chat_response.info_request(AnswerInput(ticket_text="Customer: blocked", kb_candidates=[entry])).text
    assert "profile icon" not in text and text.startswith("1. Open the policy page.")


def test_asking_for_a_ticket_is_a_request_for_a_person_and_the_offer_is_never_repeated(monkeypatch):
    from backend import graph, handoff_signals

    assert handoff_signals.asks_for_human("Yes, please raise a ticket.")
    monkeypatch.setattr(chat_response, "covers_latest", lambda data: False)
    state = {"ticket_text": "Customer: allow the widget?\nAgent (AI): Allow the servers.\nCustomer: and the limits?",
             "kb_candidates": [ENTRY.model_dump()], "recent_ai_replies": [chat_response.FOLLOWUP_NOT_COVERED], "answered": True,
             "reply_format": "chat"}
    result = graph.generate_response(state)
    assert result["ai_response"] == graph.NO_KB_REPLY_CHAT and result["needs_info"]["reason"] == "kb_no_match"


def test_a_failed_coverage_call_answers_as_before(monkeypatch):
    # Live eval: Bedrock's ServiceUnavailableException in covers_latest hit an unimported AIError (NameError).
    from backend import graph
    from backend.ai_service import AIError

    def down(*a, **k):
        raise AIError("down", provider.AIFailure(kind="network", operation="covers_latest",
                                                 code="ServiceUnavailableException"))

    monkeypatch.setattr(chat_response, "covers_latest", down)
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: "Allow the widget's servers in your policy.")
    state = {"ticket_text": "Customer: allow the widget?\nAgent (AI): Allow the servers.\nCustomer: which servers?",
             "kb_candidates": [ENTRY.model_dump()], "recent_ai_replies": ["Allow the servers."], "answered": True, "reply_format": "chat"}
    assert graph.generate_response(state)["ai_response"] == "Allow the widget's servers in your policy."


from backend.ai_service.chat_response import covers_latest as real_covers_latest  # the autouse fixture replaces the module's


def test_the_coverage_check_sees_the_previous_message_and_the_top_two_guides(monkeypatch):
    """Live probe: a Hinglish follow-up ("aur woh kahan milega?") was 'not covered' on some attempts: the
    check saw one guide and no earlier message. Scripted model: it says covered only with both."""
    second = KBCandidate(kb_entry_id="KB-2", category="SETUP", intent="Find the policy page", score=0.6,
                         instruction="Where is the policy page?", response="Open Settings > Policy.")
    seen = {}

    def model(instructions, data, schema, **k):
        seen.update(data, instructions=instructions)
        ok = "Open Settings > Policy." in data["guides"] and "policy page" in data["customer_previous_message"]
        return schema(covered=ok)

    monkeypatch.setattr(provider, "complete_json", model)
    data = AnswerInput(ticket_text="Customer: policy page kahan hai", kb_candidates=[ENTRY, second],
                       previous_message="policy page kahan hai", latest_message="aur woh kahan milega yaar?")
    assert real_covers_latest(data) is True
    assert "Hinglish" in seen["instructions"]
    assert real_covers_latest(data.model_copy(update={"previous_message": ""})) is False
    assert real_covers_latest(data.model_copy(update={"kb_candidates": [ENTRY]})) is False


def test_the_reply_context_carries_the_previous_customer_message():
    from backend import graph

    state = {"ticket_text": "Customer: policy page kahan hai\nAgent (AI): Open Settings.\nCustomer: aur woh?",
             "kb_candidates": [ENTRY.model_dump()], "category": "SETUP"}
    context = graph._reply_context(state)
    assert context["previous_message"] == "policy page kahan hai" and context["latest_message"] == "aur woh?"
