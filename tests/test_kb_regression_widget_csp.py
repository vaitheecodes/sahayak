"""Regression: a policy-error chat that went wrong live, on a synthetic page.

Live (KB drafted from a real troubleshooting page, chats with the real
model): the bot said adding "script-src 'self'" would fix a policy error
(wrong: the page's config allows two domains under two directives, with
regional domains), answered "how to check" with header advice the page
doesn't give, ended replies with "Here's how:" / "follow these steps:" and
nothing after, and showed "AI unavailable" when one call through a local
proxy failed.

Here the same shape is drafted from tests/fixtures/kb/pages/widget_csp.html
(fictional product and domains) and the same chat turns run through the
real pipeline (FastAPI, LangGraph, SQLite or Postgres) with a scripted
model that makes the same mistakes. Only the model is scripted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import db, graph, kb_retrieval, kb_store, main, topic_terms
from backend.ai_service import AIError, chat_response, provider
from kb_ingester import chunking, clean
from kb_ingester.drafting import Budget, draft_chunk
from tests.kb_ingest_helpers import ScriptedModel

PAGE = Path(__file__).parent / "fixtures" / "kb" / "pages" / "widget_csp.html"
CONFIG = ("<meta http-equiv=\"Content-Security-Policy\" content=\"script-src 'self' 'unsafe-inline' "
          "https://static.beaconrum.example.com; connect-src 'self' https://collect.beaconrum.example.com;\">")
EU = "https://static.beaconrum.example.eu"
ERROR = ("Refused to load the script 'https://static.beaconrum.example.com/beacon/beaconrum-min.js' because it "
         "violates the following Content Security Policy directive: \"script-src ...\"")
TERMS = [{"label": "Beacon RUM", "kind": "module", "aliases": []},
         {"label": "Content Security Policy", "kind": "module", "aliases": ["CSP"]}]

# What the drafting model returns for the CSP section (the live draft had no
# config at all: one vague step and an answer).
DRAFT = {"entries": [{
    "title": "Content Security Policy blocks the Beacon RUM snippet",
    "questions": ["Beacon RUM snippet blocked by my CSP?", "What CSP settings does the snippet need?",
                  "script refused because it violates the Content Security Policy",
                  "error after adding the snippet to my page"],
    "answer": ("A policy that doesn't list the Beacon RUM servers stops the snippet, so no data arrives; accounts "
               f"on European servers allow {EU} instead."),
    "kind": "troubleshooting", "steps": [], "snippets": [CONFIG], "applies_to": [], "category": "ISSUE",
}], "proposed_terms": [], "proposed_categories": []}


def _section():
    page = clean.html_to_text(PAGE.read_bytes())
    [chunk], _ = chunking.chunk_text(page.text)
    return page, chunk


def test_the_section_keeps_its_config_line_and_regional_note():
    _, chunk = _section()
    assert f"```\n{CONFIG}\n```" in chunk.text and EU in chunk.text


def test_the_draft_keeps_the_config_as_a_snippet_and_names_both_terms(monkeypatch):
    page, chunk = _section()
    ScriptedModel(DRAFT).install(monkeypatch)
    result = draft_chunk(chunk.text, heading_path=chunk.heading_path, page_title=page.title,
                         source_url="https://help.beaconrum.example.com/troubleshooting.html",
                         known_terms=TERMS, budget=Budget(2))
    [entry] = result.entries
    assert entry["snippets"] == [CONFIG] and EU in entry["answer"]
    assert entry["applies_to"] == ["Beacon RUM", "Content Security Policy"]


# ---------------------------------------------------------------------------
# The chats
# ---------------------------------------------------------------------------
class _Model:
    """Answers by operation; `answers` are popped in order."""

    def __init__(self, answers, continuation=False):
        self.answers, self.continuation, self.ops = list(answers), continuation, []

    def __call__(self, messages, **kwargs):
        system, op = messages[0]["content"], kwargs.get("operation", "")
        self.ops.append(op)
        if "You classify support tickets" in system:
            return json.dumps({"category": "ISSUE", "confidence": 0.9})
        if "is a CONTINUATION" in system:
            if callable(self.continuation):
                raise self.continuation()   # built in the request: AIError records its failure
            return json.dumps({"is_continuation": self.continuation})
        if op == "clarify":
            return "What is the exact error message you see?"
        if op == "answer":
            return self.answers.pop(0)
        if "Suggest 2-5 concrete next steps" in system:
            return json.dumps({"steps": ["Compare the customer's policy with the Beacon RUM configuration."]})
        if "taking over a chat" in system:
            return json.dumps({"issue": "Policy error after adding the snippet.", "tried": [], "findings": [],
                               "unresolved_questions": []})
        raise AssertionError(f"Unexpected AI operation {op}: {system[:80]}")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    with TestClient(main.app) as c:
        kb_retrieval.use([{**{k: v for k, v in DRAFT["entries"][0].items() if k != "applies_to"},
                           "kb_entry_id": "KB-0001", "applies_to": ["Beacon RUM", "Content Security Policy"],
                           "source_url": "https://help.beaconrum.example.com/troubleshooting.html",
                           "source_licence": "Synthetic test page"}])
        topic_terms.use(TERMS)
        yield c


def _customer(client):
    res = client.post("/api/auth/customer/signup", json={"name": "Dana Smith", "email": "dana@csp.example.com",
                                                         "password": "csp-test-password"})
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _say(client, headers, session_id, text):
    return client.post(f"/api/chats/{session_id}/messages", json={"message": text}, headers=headers).json()


def test_chat_one_gets_the_config_then_no_guide_for_how_to_check(client, monkeypatch):
    model = _Model([
        # (a) the live mistake: a partial directive, kept nowhere in the KB.
        "Your Content Security Policy is blocking the Beacon RUM script. Adding script-src 'self' should fix it. "
        f"Accounts on European servers use {EU}. Allow the Beacon RUM servers in your policy:",
        # (b) "how to check": the guide doesn't say.
        "NOT_COVERED",
    ], continuation=True)
    monkeypatch.setattr(provider, "complete", model)
    headers = _customer(client)
    chat = client.post("/api/chats", headers=headers, json={
        "issue": "I encounter an error after inserting the RUM snippet into my webpage,"}).json()
    # No symptom the KB can match yet ("RUM snippet" names no confirmed term): a question.
    assert chat["messages"][-1]["content"] == "What is the exact error message you see?"

    chat = _say(client, headers, chat["session_id"], ERROR)
    reply = chat["messages"][-1]["content"]
    assert f"```\n{CONFIG}\n```" in reply and EU in reply
    assert "https://static.beaconrum.example.com" in reply and "https://collect.beaconrum.example.com" in reply
    assert "'self' should fix" not in reply
    assert reply.startswith("Your Content Security Policy is blocking the Beacon RUM script.")

    chat = _say(client, headers, chat["session_id"], "how to check")
    # The guide doesn't say how to check a policy: said plainly, then a ticket.
    assert [m["content"] for m in chat["messages"]][-2] == graph.NO_KB_REPLY_CHAT
    assert chat["status"] == "escalated" and chat["ticket_id"] in chat["messages"][-1]["content"]
    assert "HTTP headers" not in json.dumps(chat["messages"])


def test_chat_two_never_ends_on_a_lead_in_and_survives_a_dropped_call(client, monkeypatch):
    model = _Model([
        # (a) + (c): an invented directive, then steps the KB doesn't give.
        "To add \"script-src 'self'\" to your Content Security Policy, follow these steps:\n"
        "1. Open your server config.\n2. Add script-src 'self'.",
        "Your policy has to allow the Beacon RUM servers, as below:",
        "Add the line below to the head of your pages, or the same two directives to your policy header:",
    ], continuation=lambda: AIError("Could not reach Bedrock", provider.AIFailure(
        kind="network", operation="ContinuationVerdict", code="ProxyConnectionError")))
    monkeypatch.setattr(provider, "complete", model)
    headers = _customer(client)
    chat = client.post("/api/chats", headers=headers, json={"issue": f"I encounter an error after in{ERROR}"}).json()
    reply = chat["messages"][-1]["content"]
    assert "follow these steps" not in reply and "'self'\"" not in reply
    assert reply.startswith("Your policy has to allow the Beacon RUM servers, as below:")
    assert f"```\n{CONFIG}\n```" in reply

    # (d) The continuation check's connection drops: the turn still gets an answer.
    chat = _say(client, headers, chat["session_id"], "how to add give me steps")
    assert not chat.get("ai_error") and chat["status"] == "active"
    reply = chat["messages"][-1]["content"]
    assert reply.startswith("Add the line below") and f"```\n{CONFIG}\n```" in reply
    conn = db.get_connection()
    try:
        details = [json.loads(r["detail"]) for r in conn.execute(
            "SELECT detail FROM audit_events WHERE action = 'chat.ai_failure' AND entity_id = ?",
            (chat["session_id"],))]
    finally:
        conn.close()
    assert {"kind": "network", "outcome": "fallback"}.items() <= next(d for d in details if d["kind"] == "network").items()
    assert any(d["code"] in ("ungrounded_values", "only_ungrounded_steps") for d in details)


def test_every_reply_of_the_flow_is_checked_by_code_not_by_the_prompt():
    """The prompt rules are a request; these are the guarantees."""
    entry = chat_response.KBCandidate(kb_entry_id="KB-0001", category="ISSUE", intent="x", instruction="x",
                                      response=f"{DRAFT['entries'][0]['answer']}\n{CONFIG}", score=0.9,
                                      snippets=[CONFIG])
    data = chat_response.AnswerInput(ticket_text=f"Customer: {ERROR}", kb_candidates=[entry], customer_text=ERROR)
    text = chat_response._frame("Your policy has to allow the Beacon RUM servers for the snippet to load. "
                                "Adding script-src 'self' should fix it. Allow the servers below:", data, "answer").text
    assert "'self' should fix" not in text and text.startswith("Your policy has to allow")
    assert "Allow the servers below:\n\n```" in text
    assert kb_store.response_text({"answer": "a", "snippets": [CONFIG]}).endswith(CONFIG)
