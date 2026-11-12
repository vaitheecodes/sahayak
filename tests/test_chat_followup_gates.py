"""Integration tests for the AI chat's per-message gates
(backend/conversation.followup_gate, applied by backend/chats.py):
closing acknowledgment and continuation.

Bug 1 (closing ack): every chat message re-invoked the full
classify_ticket/decide_route pipeline, so a bare "thanks" after an answer
got classified with near-zero confidence and wrongly escalated. Now a
bare closing acknowledgment after an AI answer resolves the chat (the
customer confirmed it) without re-running the pipeline.

Bug 2 (continuation): an on-topic follow-up ("what is the difference")
was classified in isolation, collapsed confidence, and escalated. A
message that refers back to the AI's own last reply skips
classify_ticket/decide_route and is answered via generate_response —
unless it carries escalation language (negation/offensive/coordinated),
which must still hit decide_route's hard override.

Real temporary SQLite DB via FastAPI's TestClient; the pipeline is a stub
that records invocations (backend.runtime.set_graph), and
graph.is_continuation_of_prior_response / graph.generate_response are
monkeypatched where a test needs to control the continuation path.
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from backend import chats, db, graph, main, runtime

_email_counter = itertools.count()


class _StubGraph:
    """Returns pre-programmed results in order and records every
    invocation, so tests can assert whether the pipeline was re-run."""

    def __init__(self, results):
        self._results = list(results)
        self.invocations = []

    def invoke(self, state):
        self.invocations.append(state)
        return self._results.pop(0)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    with TestClient(main.app) as c:
        yield c


def _signup(client) -> dict:
    email = f"chat-gates-{next(_email_counter)}@example.com"
    res = client.post(
        "/api/auth/customer/signup",
        json={"name": "Test Customer", "email": email, "password": "pw123456"},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _start_chat(client, headers, first_result, issue="how do I install the Brightdesk app"):
    stub = _StubGraph([first_result])
    runtime.set_graph(stub)
    res = client.post("/api/chats", json={"issue": issue}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json(), stub


def _send(client, headers, session_id, message):
    res = client.post(f"/api/chats/{session_id}/messages", json={"message": message}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


_ANSWERED = {
    "route": "ai",
    "category": "SETUP",
    "confidence": 0.95,
    "ai_response": "Here's how to install the Brightdesk app...",
    "clarification_attempts": 0,
}
_ESCALATE = {
    "route": "human",
    "category": "SETUP",
    "confidence": 0.3,
    "ai_response": None,
    "clarification_attempts": 0,
}


def test_bare_thanks_after_answer_keeps_the_chat_open_and_that_worked_closes_it(client):
    # docs/CHAT_CONTRACT.md rule 7: "thanks" / "ok" / "hmm" never close the chat.
    headers = _signup(client)
    chat, stub = _start_chat(client, headers, _ANSWERED)
    calls_before = len(stub.invocations)
    for ack in ("thanks", "ok", "hmm"):
        after = _send(client, headers, chat["session_id"], ack)
        assert after["status"] == "active" and after["messages"][-1]["content"] == chats.ACK_REPLY
    assert len(stub.invocations) == calls_before                  # no model, no pipeline

    after = _send(client, headers, chat["session_id"], "that worked, thanks")
    assert after["status"] == "resolved" and after["ticket_id"] is None
    assert len(stub.invocations) == calls_before


def test_resolved_chat_rejects_further_messages(client):
    headers = _signup(client)
    chat, _ = _start_chat(client, headers, _ANSWERED)
    _send(client, headers, chat["session_id"], "that worked")

    res = client.post(
        f"/api/chats/{chat['session_id']}/messages", json={"message": "hello again"}, headers=headers
    )
    assert res.status_code == 400


def test_thanks_after_a_clarifying_question_is_not_a_resolution(client, monkeypatch):
    """Nothing was answered yet, so "thanks" can't confirm a resolution."""
    headers = _signup(client)
    clarify = {**_ANSWERED, "route": "clarify", "ai_response": "Which OS?", "clarification_attempts": 1}
    chat, stub = _start_chat(client, headers, clarify)
    stub._results.append(_ANSWERED)

    after = _send(client, headers, chat["session_id"], "thanks")
    assert after["status"] == "active"
    assert len(stub.invocations) == 2


def test_substantive_followup_after_answer_still_reruns_pipeline(client):
    """"thanks, but it's still not working" is not a bare acknowledgment;
    it falls through to the pipeline, which here escalates."""
    headers = _signup(client)
    chat, stub = _start_chat(client, headers, _ANSWERED)
    stub._results.append(_ESCALATE)

    calls_before = len(stub.invocations)
    after = _send(client, headers, chat["session_id"], "thanks, but it's still not working")

    assert len(stub.invocations) == calls_before + 1
    assert after["status"] == "escalated"
    assert after["ticket_id"]


def test_question_after_answer_never_treated_as_closing_ack(client, monkeypatch):
    headers = _signup(client)
    chat, stub = _start_chat(client, headers, _ANSWERED)
    monkeypatch.setattr(graph, "is_continuation_of_prior_response", lambda *a, **k: False)
    stub._results.append({**_ANSWERED, "ai_response": "Sure, here's more detail..."})

    calls_before = len(stub.invocations)
    after = _send(client, headers, chat["session_id"], "what about Windows?")

    assert len(stub.invocations) == calls_before + 1
    assert after["status"] == "active"
    assert after["messages"][-1]["content"] == "Sure, here's more detail..."


def test_continuation_question_answers_directly_without_reinvoking_pipeline(client, monkeypatch):
    headers = _signup(client)
    chat, stub = _start_chat(client, headers, _ANSWERED)
    monkeypatch.setattr(graph, "is_continuation_of_prior_response", lambda *a, **k: True)
    monkeypatch.setattr(
        graph, "generate_response", lambda state: {"ai_response": "Here's the difference..."}
    )

    calls_before = len(stub.invocations)
    after = _send(client, headers, chat["session_id"], "what is the differnce")

    assert len(stub.invocations) == calls_before
    assert after["status"] == "active"
    assert [m["role"] for m in after["messages"][-2:]] == ["customer", "ai"]
    assert after["messages"][-1]["content"] == "Here's the difference..."


def test_continuation_generate_response_told_it_is_a_continuation(client, monkeypatch):
    headers = _signup(client)
    chat, _ = _start_chat(client, headers, _ANSWERED)
    captured = []

    def _fake_generate_response(state):
        captured.append(state)
        return {"ai_response": "..."}

    monkeypatch.setattr(graph, "is_continuation_of_prior_response", lambda *a, **k: True)
    monkeypatch.setattr(graph, "generate_response", _fake_generate_response)

    _send(client, headers, chat["session_id"], "what is the differnce")
    assert len(captured) == 1
    assert captured[0]["continuation"] is True
    assert captured[0]["category"] == _ANSWERED["category"]
    assert captured[0]["reply_format"] == "chat"


def test_escalation_language_blocks_continuation_shortcut(client, monkeypatch):
    headers = _signup(client)
    chat, stub = _start_chat(client, headers, _ANSWERED)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("continuation check must be skipped for escalation language")

    monkeypatch.setattr(graph, "is_continuation_of_prior_response", _fail_if_called)
    stub._results.append(_ESCALATE)

    calls_before = len(stub.invocations)
    after = _send(client, headers, chat["session_id"], "thanks, but it's still not working")
    assert len(stub.invocations) == calls_before + 1
    assert after["status"] == "escalated"


def test_genuinely_new_topic_reruns_pipeline(client, monkeypatch):
    headers = _signup(client)
    chat, stub = _start_chat(client, headers, _ANSWERED)
    monkeypatch.setattr(graph, "is_continuation_of_prior_response", lambda *a, **k: False)
    stub._results.append({**_ANSWERED, "ai_response": "To install the agent on Ubuntu..."})

    calls_before = len(stub.invocations)
    after = _send(client, headers, chat["session_id"], "separately, how do I install the agent on Ubuntu")
    assert len(stub.invocations) == calls_before + 1
    assert after["status"] == "active"


def test_a_failed_continuation_check_goes_down_the_normal_path(client, monkeypatch):
    """The continuation check is only a shortcut: a dropped connection (a
    local proxy refusing one call) must not fail the turn ("AI assistant is
    unavailable"); the message is classified as new, and the failure is
    recorded with outcome "fallback"."""
    from backend.ai_service import AIError, provider

    headers = _signup(client)
    chat, stub = _start_chat(client, headers, _ANSWERED)

    def _proxy_down(*args, **kwargs):
        raise AIError("Could not reach Bedrock", provider.AIFailure(
            kind="network", operation="ContinuationVerdict", code="ProxyConnectionError"))

    monkeypatch.setattr(graph, "is_continuation_of_prior_response", _proxy_down)
    stub._results.append({**_ANSWERED, "ai_response": "Open Settings and pick a region."})

    calls_before = len(stub.invocations)
    after = _send(client, headers, chat["session_id"], "which region should I pick?")
    assert len(stub.invocations) == calls_before + 1
    assert after["status"] == "active" and not after.get("ai_error")
    conn = db.get_connection()
    try:
        details = [row["detail"] for row in conn.execute(
            "SELECT detail FROM audit_events WHERE action = 'chat.ai_failure' AND entity_id = ?",
            (chat["session_id"],))]
    finally:
        conn.close()
    assert any('"network"' in d and '"fallback"' in d for d in details)


def test_a_greeting_gets_a_greeting_and_the_real_question_becomes_the_problem_text(client):
    # docs/CHAT_CONTRACT.md rule 2 (chat eval seed: "hi" then a question escalated at once).
    headers = _signup(client)
    stub = _StubGraph([_ANSWERED])
    runtime.set_graph(stub)
    chat = client.post("/api/chats", json={"issue": "hi"}, headers=headers).json()
    assert chat["status"] == "active" and chat["messages"][-1]["content"] == chats.greeting()
    assert stub.invocations == []                                   # no model, no KB lookup
    after = _send(client, headers, chat["session_id"], "how do I install the Brightdesk app")
    assert after["status"] == "active" and after["issue"] == "how do I install the Brightdesk app"
    assert len(stub.invocations) == 1
