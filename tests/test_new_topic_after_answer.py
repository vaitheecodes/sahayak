"""Live demo, chat B: after a real answer, a NEW topic with a strong KB match ("not loading" in a CSP
question, entry scored 0.77) was escalated because of the negation tag; and "It's not working" tacked onto a
question about the RUM script pulled the lookup to "Why is my RUM not working?". Scripted model.

- negation fires only when the message points back at the answer, or its best entry is the entry just answered;
- "working" is not searched when two other content words are left.
"""

from __future__ import annotations

from backend import graph, kb_retrieval
from tests.test_how_to_flow import ANSWER, _ai_lines, _chat, _customer, _send, client  # noqa: F401

PAYSLIP = "My payslip is not loading, my payslip is not showing for this month"


def test_a_new_topic_with_a_strong_match_is_answered_not_escalated(client):
    headers = _customer(client)
    chat = _chat(client, headers, "How do I apply for leave?")
    assert _ai_lines(chat) == [ANSWER]
    chat = _send(client, headers, chat, PAYSLIP)
    assert chat["status"] == "active" and chat["ticket_id"] is None and "year filter" in _ai_lines(chat)[-1]


def test_pointing_back_at_the_answer_still_escalates(client):
    headers = _customer(client)
    chat = _chat(client, headers, "How do I apply for leave?")
    chat = _send(client, headers, chat, "I tried that and my payslip is not loading either")
    assert chat["status"] == "escalated"


def test_the_same_entry_again_still_escalates(client):
    headers = _customer(client)
    chat = _chat(client, headers, PAYSLIP)
    assert chat["status"] == "active" and chat["ticket_id"] is None
    chat = _send(client, headers, chat, "my payslip is not showing for this month")
    assert chat["status"] == "escalated"


def test_a_symptom_filler_does_not_pull_the_lookup_to_a_short_question():
    kb_retrieval.use([
        {"kb_entry_id": "KB-1", "title": "Check the script", "category": "USAGE", "kind": "how-to",
         "questions": ["How do I verify the RUM script is on my webpage?"], "answer": "Look.", "steps": []},
        {"kb_entry_id": "KB-2", "title": "Connection", "category": "USAGE", "kind": "how-to",
         "questions": ["Why is my RUM not working?"], "answer": "Connect.", "steps": []},
    ])
    top = lambda q: kb_retrieval.retrieve_candidates(q, top_k=1)[0].entry.kb_entry_id
    assert top("How can I verify the RUM script on my webpage? It's not working") == "KB-1"
    assert top("My RUM is not working") == "KB-2"        # nothing else to search: the words stay
