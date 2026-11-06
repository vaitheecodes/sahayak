"""Tests for the continuation-vs-new-topic pieces in backend/graph.py
that back the "what is the difference" bug fix (see
tests/test_ticket_chat_closing.py for the endpoint-level integration
tests of the full fix).

is_continuation_of_prior_response makes a real LLM call, so it's tested
here with a stubbed Azure OpenAI client (prompt-construction /
response-parsing only, no network) — same pattern as
tests/test_ask_clarifying_question.py. has_escalation_language and
retrieve_kb_candidates_for_continuation are pure/DB-free and tested
directly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import graph  # noqa: E402
from backend.ai_service import provider  # noqa: E402
from tests import kb_fixture  # noqa: E402


def _invoke_is_continuation(monkeypatch, response_json, message_text, prior_ai_response):
    captured: list[dict] = []

    def _fake_complete(messages, **kwargs):
        captured.append({"messages": messages, "kwargs": kwargs})
        return response_json

    monkeypatch.setattr(provider, "complete", _fake_complete)
    result = graph.is_continuation_of_prior_response(message_text, prior_ai_response)
    assert captured, "expected the provider to be called"
    return result, captured[0]


def test_continuation_true_is_parsed(monkeypatch):
    result, call = _invoke_is_continuation(
        monkeypatch,
        json.dumps({"is_continuation": True}),
        "what is the differnce",
        "Casual leave is planned ahead; Sick leave can be applied for afterwards.",
    )
    assert result is True
    # grounding check: both the new message and the prior reply must
    # actually be in the prompt sent to the model
    user_content = call["messages"][1]["content"]
    assert "what is the differnce" in user_content
    assert "Sick leave" in user_content


def test_continuation_false_is_parsed(monkeypatch):
    result, _ = _invoke_is_continuation(
        monkeypatch,
        json.dumps({"is_continuation": False}),
        "separately, how do I install the app on Android",
        "Casual leave is planned ahead; Sick leave can be applied for afterwards.",
    )
    assert result is False


def test_missing_key_defaults_to_false(monkeypatch):
    result, _ = _invoke_is_continuation(monkeypatch, json.dumps({}), "hmm", "prior reply")
    assert result is False


def test_uses_json_mode_and_zero_temperature(monkeypatch):
    _, call = _invoke_is_continuation(
        monkeypatch, json.dumps({"is_continuation": True}), "msg", "prior"
    )
    assert call["kwargs"]["json_mode"] is True
    assert call["kwargs"]["temperature"] == 0


# ---------------------------------------------------------------------------
# has_escalation_language
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "thanks, but it's still not working",
        "this is useless and ridiculous",
        "not resolved, and also still broken, so I guess that's it then",
    ],
)
def test_escalation_language_detected(text):
    assert graph.has_escalation_language(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "what is the differnce",
        "how do I install the app on Android",
        "thanks, that worked",
    ],
)
def test_no_escalation_language(text):
    assert graph.has_escalation_language(text) is False


# ---------------------------------------------------------------------------
# retrieve_kb_candidates_for_continuation
# ---------------------------------------------------------------------------
@pytest.fixture()
def kb():
    kb_fixture.load()


def test_continuation_retrieval_uses_the_customers_earlier_messages(kb):
    """A short fragment alone ("what is the differnce") has almost no
    topic vocabulary; the customer's earlier messages carry the topic."""
    transcript = (
        "Customer: I want to export the attendance report\n"
        "Agent (AI): Attendance reports can be exported as CSV or Excel.\n"
        "Customer: what is the differnce"
    )
    candidates = graph.retrieve_kb_candidates_for_continuation(transcript)
    assert candidates
    assert candidates[0]["kb_entry_id"] == "KB-0006"


def test_continuation_retrieval_never_searches_the_ai_reply(kb):
    """The AI's previous reply talks about installing the mobile app; the
    customer only ever talked about the attendance report. Retrieval
    follows the customer, and the AI's wording can't raise any score."""
    ai_reply = ("To install the Brightdesk app on Android, search Google Play, install the "
                "app and sign in.")
    customer_only = "Customer: I want to export the attendance report\nCustomer: can you say more"
    with_ai = ("Customer: I want to export the attendance report\n"
               f"Agent (AI): {ai_reply}\n1. Open Google Play.\n2. Install the app on Android.\n"
               "Customer: can you say more")
    assert graph.retrieve_kb_candidates_for_continuation(with_ai) == \
        graph.retrieve_kb_candidates_for_continuation(customer_only)
    assert all(c["kb_entry_id"] != "KB-0002"
               for c in graph.retrieve_kb_candidates_for_continuation(with_ai))


def test_continuation_retrieval_with_only_a_vague_fragment_finds_no_match(kb):
    transcript = ("Customer: hello\nAgent (AI): How do I install the app on Android? Use Google Play.\n"
                  "Customer: can you say more about that")
    assert graph.retrieve_kb_candidates_for_continuation(transcript) == []


def test_continuation_retrieval_returns_dicts_shaped_like_normal_retrieval(kb):
    candidates = graph.retrieve_kb_candidates_for_continuation(
        "Customer: how do I install the app on android\nAgent (AI): Use Google Play.\n"
        "Customer: can you say more about that")
    assert candidates
    for key in ("kb_entry_id", "category", "intent", "instruction", "response", "score"):
        assert key in candidates[0]
