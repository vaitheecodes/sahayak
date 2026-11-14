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


