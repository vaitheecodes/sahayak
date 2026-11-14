"""Every specific value in a reply comes from the KB entry or the customer.

Seen in a live chat: with no KB entry for a policy error, the bot said
adding "script-src 'self'" would fix it (wrong), and answered "how do I
check?" with steps the guide doesn't give. Now:
- grounding.ground_values drops a sentence carrying a domain/URL, a
  directive (with its whole source list), quoted or backticked text, a
  path, or a version/port/limit number that neither the KB text nor the
  customer's own messages contain; ordinary sentences pass untouched;
- a reply that loses most of its text is regenerated, then falls back;
- a fault report no KB entry covers is never answered: clarifying
  questions, then "no guide" and a ticket; an entry that doesn't cover the
  latest message makes the model say NOT_COVERED, which hands off too.
"""

from __future__ import annotations

import pytest

from backend import graph
from backend.ai_service import chat_response, provider
from backend.ai_service.grounding import ground_values, value_problem
from backend.ai_service.schemas import AnswerInput, ClarifyInput, KBCandidate

KB_TEXT = ("How do I allow the widget under my content policy?\n"
           "Allow the widget's servers in your policy: "
           "script-src 'self' https://cdn.example.com; connect-src 'self' https://collect.example.com\n"
           "Open Settings > Region and pick your region.")
CUSTOMER = ("Refused to load the script 'https://cdn.example.com/widget.js' because it violates "
            "the following directive: \"script-src ...\"")
ALLOWED = f"{KB_TEXT}\n{CUSTOMER}"


@pytest.mark.parametrize("sentence", [
    "Wait about 2 minutes and reload the page.",
    "Step 1 is opening Settings.",
    "Brightdesk HR keeps your region setting.",
    "Node.js and Brightdesk HR are both fine here.",
    "The address you pasted, https://cdn.example.com/widget.js, is the one being blocked.",
    "Try again in 10 seconds.",
    "Your policy needs script-src 'self' https://cdn.example.com for the widget to load.",
    "Allow https://cdn.example.com under script-src.",
    "Open Settings > Region and pick your region.",
    "It's the customer's own policy that blocks it, isn't it?",
])
def test_ordinary_and_grounded_sentences_pass_untouched(sentence):
    assert value_problem(sentence, ALLOWED) is None
    assert ground_values(sentence, ALLOWED) == (sentence, [])


@pytest.mark.parametrize("sentence", [
    "Adding script-src 'self' should fix it.",                      # a partial source list
    "Allow https://static.example.org in your policy.",            # an invented domain
    "Allow eu.example.net as well.",
    "Run `sudo systemctl restart widget` and retry.",                # a command
    "Edit /etc/nginx/conf.d/site.conf and reload.",                 # a path
    "Upgrade to version 2.4.1 first.",
    "Open port 8443 on your firewall.",
    "The limit is 500 requests a day.",
    "Files up to 25 MB are accepted.",
    "Look for the \"Content-Security-Policy-Report-Only\" header.",  # quoted text the KB lacks
])
def test_sentences_with_values_nobody_gave_are_dropped(sentence):
    problem = value_problem(sentence, ALLOWED)
    assert problem
    assert ground_values(f"Your policy blocks it. {sentence}", ALLOWED) == (
        "Your policy blocks it.", [(sentence, problem)])


def test_a_step_line_with_an_invented_value_is_dropped():
    text = "Do this:\n1. Open Settings > Region.\n2. Add `report-uri /csp` to the policy."
    assert ground_values(text, ALLOWED) == ("Do this:\n1. Open Settings > Region.",
                                            [("2. Add `report-uri /csp` to the policy.", "report-uri /csp")])


KB = KBCandidate(kb_entry_id="KB-0001", category="ISSUE", intent="policy", score=0.7,
                 instruction="How do I allow the widget under my content policy?",
                 response=KB_TEXT.split("\n", 1)[1])


def _answer(monkeypatch, *replies, kb=(KB,)):
    replies = iter(replies)
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: next(replies))
    return chat_response.answer(AnswerInput(ticket_text=f"Customer: {CUSTOMER}", kb_candidates=list(kb),
                                            customer_text=CUSTOMER, latest_message=CUSTOMER))


def test_the_invented_directive_sentence_is_dropped_from_an_answer(monkeypatch):
    log = provider.start_failure_log()
    reply = _answer(monkeypatch, "Your policy blocks the widget. Adding script-src 'self' should fix it. "
                                 "Allow https://cdn.example.com under script-src and https://collect.example.com "
                                 "under connect-src.")
    assert "'self' should fix" not in reply.text and "https://collect.example.com" in reply.text
    # "Adding script-src 'self' should fix it" is an instruction the entry doesn't give: dropped first.
    assert [(f.code, f.outcome) for f in log] == [("ungrounded_steps", "filtered")]


def test_a_reply_that_is_mostly_invented_values_is_regenerated(monkeypatch):
    log = provider.start_failure_log()
    reply = _answer(monkeypatch, "Fine. Run `curl -I https://your.site` and look for report-uri /csp.",
                    "Allow https://cdn.example.com under script-src.")
    assert reply.text == "Allow https://cdn.example.com under script-src."
    assert [(f.code, f.outcome) for f in log] == [("ungrounded_values", "regenerated")]


def test_the_answer_prompt_asks_for_not_covered_only_with_a_kb_entry(monkeypatch):
    seen = []
    monkeypatch.setattr(provider, "complete_text", lambda instructions, *a, **k: seen.append(instructions) or "Ok.")
    chat_response.answer(AnswerInput(ticket_text="Customer: x", kb_candidates=[KB]))
    chat_response.answer(AnswerInput(ticket_text="Customer: x"))
    assert chat_response.NOT_COVERED in seen[0] and chat_response.NOT_COVERED not in seen[1]


def _state(**extra):
    return {"ticket_text": f"Customer: {CUSTOMER}\nAgent (AI): Your policy blocks it.\nCustomer: how to check",
            "category": "ISSUE", "reply_format": "chat", **extra}


def test_an_entry_that_does_not_cover_the_question_hands_off(monkeypatch):
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: "NOT_COVERED")
    out = graph.generate_response(_state(kb_candidates=[KB.model_dump()]))
    assert out["ai_response"] == graph.NO_KB_REPLY_CHAT
    assert out["needs_info"]["reason"] == "kb_no_match"


def test_a_report_without_a_kb_entry_is_never_answered(monkeypatch):
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: pytest.fail("no model call"))
    out = graph.generate_response(_state(kb_candidates=[]))
    assert out["ai_response"] == graph.NO_KB_REPLY_CHAT and out["needs_info"]["reason"] == "kb_no_match"


def test_a_confident_report_without_a_kb_entry_is_clarified_then_handed_off():
    state = _state(confidence=0.95, kb_candidates=[], language_tags=[])
    first = graph.decide_route({**state, "clarification_attempts": 0})
    assert first["route"] == "clarify" and first["clarification_attempts"] == 1
    last = graph.decide_route({**state, "clarification_attempts": 3})
    assert last["route"] == "ai" and "no guide" in last["route_reason"]
    with_entry = graph.decide_route({**state, "clarification_attempts": 0, "kb_candidates": [KB.model_dump()]})
    assert with_entry["route"] == "ai"


# A URL lives in ONE entry: another candidate's URL (or an invented path on a grounded host) never passes.
RUM_URL = "https://col.site24x7rum.com/rum/connect"
RUM_ENTRY = KBCandidate(kb_entry_id="KB-0004", category="ISSUE", intent="connectivity", score=0.5,
                        instruction="How do I verify my browser can reach the servers?",
                        response=f"1. Navigate to {RUM_URL} to verify connectivity.")


def _ask(monkeypatch, text, candidates):
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: text)
    return chat_response.clarify(ClarifyInput(ticket_text="Customer: it is not loading", kb_candidates=candidates,
                                              customer_text="it is not loading", latest_message="it is not loading"))


def test_a_url_from_another_candidate_is_dropped_from_a_question(monkeypatch):
    reply = _ask(monkeypatch, f"Is the page completely blank, or does only part of it fail to load for you? Visit {RUM_URL} to check.", [KB, RUM_ENTRY])
    assert "rum/connect" not in reply.text and "Is the page completely blank" in reply.text


def test_an_invented_path_on_a_grounded_host_is_dropped_from_an_answer(monkeypatch):
    entry = RUM_ENTRY.model_copy(update={"response": "1. Navigate to https://col.site24x7rum.com/rum/beacon to verify connectivity."})
    reply = _answer(monkeypatch, "Your page is blank. Navigate to https://col.site24x7rum.com/rum/beacon to verify connectivity. "
                                 f"Navigate to {RUM_URL} to verify connectivity.", kb=(entry,))
    assert "rum/connect" not in reply.text and "rum/beacon" in reply.text


def test_the_answering_entrys_own_url_still_passes(monkeypatch):
    reply = _answer(monkeypatch, f"Navigate to {RUM_URL} to verify connectivity.", kb=(RUM_ENTRY,))
    assert RUM_URL in reply.text
