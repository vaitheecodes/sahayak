"""A reply never ends with a sentence promising steps that don't follow.

Seen in a live chat: every step was dropped as unsupported by the KB
(backend/ai_service/grounding.py) and "Here's how:" / "follow these
steps:" was left with nothing under it.
"""

from __future__ import annotations

import pytest

from backend.ai_service import chat_response, provider
from backend.ai_service.grounding import strip_dangling_lead_ins
from backend.ai_service.schemas import AnswerInput, KBCandidate

KB = KBCandidate(kb_entry_id="KB-0001", category="ISSUE", intent="connectivity",
                 instruction="How do I check the connection?", response="Open https://status.example.com/connect to check the connection.", score=0.6)

HOW_TO_CHECK = (
    "To check if your website has a Content Security Policy (CSP) in place, you can inspect the HTTP "
    "headers of your website. Here's how:\n"
    "1. Open your browser's developer tools (F12).\n"
    "2. Go to the Network tab and reload the page.\n"
    "3. Select the document request and look for the Content-Security-Policy response header.")
HOW_TO_ADD = ("To add \"script-src 'self'\" to your Content Security Policy, follow these steps:\n"
              "1. Open your server config.\n2. Add script-src 'self'.")


@pytest.mark.parametrize("raw, expected", [
    ("Some advice. Here's how:", "Some advice."),
    ("Some advice. Follow these steps:", "Some advice."),
    ("Here is how to fix it:\n\n", ""),
    ("Do the following.\nThen tell me what you see.", "Then tell me what you see."),
])
def test_dangling_lead_ins_are_removed(raw, expected):
    assert strip_dangling_lead_ins(raw) == expected


@pytest.mark.parametrize("text", [
    "Here's how:\n1. Open Settings.\n2. Pick a region.",
    "Follow these steps:\n\n- Open Settings\n- Pick a region",
    "The error you saw:\n\"Refused to load the script\"\nDoes it appear on every page?",
    "Wait about 2 minutes and reload the page.",
    "Step 1 is done when the page shows a green tick.",
])
def test_lead_ins_with_something_after_them_stay(text):
    assert strip_dangling_lead_ins(text) == text


def _answer(monkeypatch, reply, reply_format="chat"):
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: reply)
    return chat_response.answer(AnswerInput(ticket_text="Customer: how to check", kb_candidates=[KB],
                                            customer_name="Dana Smith", reply_format=reply_format)).text


def test_the_live_how_to_check_reply_loses_its_dangling_lead_in(monkeypatch):
    text = _answer(monkeypatch, HOW_TO_CHECK)
    assert "Here's how" not in text and not text.rstrip().endswith(":")
    assert "1." not in text


def test_the_live_how_to_add_reply_is_regenerated_then_falls_back(monkeypatch):
    """Only a lead-in is left: our own check rejects it, never "AI unavailable"."""
    log = provider.start_failure_log()
    text = _answer(monkeypatch, HOW_TO_ADD)
    assert "follow these steps" not in text and not text.rstrip().endswith(":")
    assert ("filter_rejected", "only_lead_in") in [(f.kind, f.code) for f in log]


def test_email_replies_lose_dangling_lead_ins_too(monkeypatch):
    text = _answer(monkeypatch, HOW_TO_CHECK, reply_format="email")
    assert "Here's how" not in text and text.startswith("Hi Dana,")
