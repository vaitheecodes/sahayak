"""A covering KB entry exists, yet the bot said "I don't have a guide for that
yet" (chat eval 20261113-223545, six conversations). Three causes:

- "I'm trying to connect my Slack account to Brightdesk": the contraction's
  "m" and the filler "trying" counted as the customer's subject, so the how-to
  guide (a strong match) no longer shared half of their words.
- "I need help with my phone app": the Android / iOS guides stayed gated and
  the model-written question didn't ask which; after it, "no guide". A report
  now gets the same ONE fixed question as a how-to, and a "yes" to a
  one-option question names the option.
- A Hinglish follow-up the model rewrote to the exact topic title: titles
  weren't searched, so the entry never matched its own title.

Real app, pipeline, retrieval on the neutral test KB; scripted model.
"""

from __future__ import annotations

import pytest

from backend import graph, kb_retrieval, request_kind
from backend.ai_service import rewrite_query
from tests import kb_fixture
from tests.test_how_to_flow import ANSWER, _ai_lines, _chat, _customer, _send, client  # noqa: F401


def test_a_contraction_and_a_lead_in_are_no_subject_words():
    kb_fixture.load()
    assert graph.informative_words("I'm trying to connect my Slack account to Brightdesk.") == [
        "connect", "slack", "account"]
    assert graph.informative_words("I've been attempting to export it") == ["export"]


def test_a_how_to_with_a_lead_in_is_answered_from_its_guide(client):
    chat = _chat(client, _customer(client), "I'm trying to connect my Slack account to Brightdesk.")
    assert chat["status"] == "active" and _ai_lines(chat) == [ANSWER]
    assert "answer" in client.model.ops()


def test_a_report_the_platform_guides_cover_gets_the_one_fixed_question_then_the_guide(client):
    headers = _customer(client)
    chat = _chat(client, headers, "I need help with my phone app.")
    question = graph.HOW_TO_VARIANT_QUESTION.format(options="Android or iOS")
    assert chat["status"] == "active" and _ai_lines(chat) == [question]
    assert "clarify" not in client.model.ops()          # fixed text, no model-written question
    assert chat["answered"] is False                     # a question is not an answer
    chat = _send(client, headers, chat, "Android")
    assert chat["status"] == "active" and _ai_lines(chat)[1:] == [ANSWER]


def test_the_variant_question_is_never_asked_twice_and_is_not_asked_without_a_guide(client):
    headers = _customer(client)
    chat = _chat(client, headers, "I need help with my phone app.")
    chat = _send(client, headers, chat, "not sure")
    assert len(_ai_lines(chat)) == 2 and "Which one is it?" not in _ai_lines(chat)[1]
    # No guide on the subject: no variant question either.
    chat = _chat(client, headers, "I need help with the quarterly bonus calculator")
    assert "I have a guide for" not in _ai_lines(chat)[0]


def test_a_word_all_the_guides_share_is_no_reason_to_ask_which_platform(client):
    """Chat eval: "connecting my messaging app" matched the Android / iOS install guides on "app" alone
    and was asked Android or iOS; the customer meant Slack."""
    chat = _chat(client, _customer(client), "I need help with connecting my messaging app to Brightdesk.")
    assert "Android or iOS" not in _ai_lines(chat)[0] and "I have a guide for" not in _ai_lines(chat)[0]


@pytest.mark.parametrize("text, yes", [("Yes", True), ("Yes, the mobile app.", True), ("yeah that's it", True),
                                       ("No, iPhone", False), ("Yes and no", False), ("not sure", False),
                                       ("yes I tried it but it did not work for me at all", False)])
def test_a_yes_is_a_short_affirmative_without_a_no(text, yes):
    assert request_kind.is_affirmative(text) is yes


def test_a_yes_to_the_one_option_question_names_that_option():
    kb_fixture.load()
    asked = graph.HOW_TO_ONE_VARIANT_QUESTION.format(option="Android")
    text = f"Customer: I need help with my phone app\nAgent (AI): {asked}\nCustomer: Yes, the mobile app."
    state = {"ticket_text": text}
    state.update(graph.retrieve_kb_candidates(state))
    assert [c["kb_entry_id"] for c in graph.grounding_candidates(state)[0]][:1] == ["KB-0002"]
    # "No" doesn't, and neither does a yes to some other question.
    no = {"ticket_text": text.replace("Yes, the mobile app.", "No, iPhone")}
    no.update(graph.retrieve_kb_candidates(no))
    assert "KB-0002" not in [c["kb_entry_id"] for c in graph.grounding_candidates(no)[0]]
    other = {"ticket_text": text.replace(asked, "Is it the mobile app?")}
    other.update(graph.retrieve_kb_candidates(other))
    assert graph.grounding_candidates(other)[0] == []


