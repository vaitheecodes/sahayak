"""Tests for backend/graph.py's decide_route — the three-way routing
policy (ai / clarify / human). Pure function, no LLM/DB calls, so these
run fast and deterministically.

Note: importing backend.graph does initialize an AzureOpenAI client at
module scope, which requires AZURE_OPENAI_ENDPOINT/API_KEY/DEPLOYMENT to
be set (loaded from .env) even though decide_route itself never calls it.

Run with: pytest tests/test_decide_route.py
"""

from __future__ import annotations

import sys

import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import app_settings  # noqa: E402
from backend.graph import decide_route  # noqa: E402

# The routing policy is admin-editable (backend/app_settings.py); these
# tests run against its defaults.
_POLICY = app_settings.RoutingSettings()
CONFIDENCE_THRESHOLD = _POLICY.confidence_threshold
HIGH_RISK_CONFIDENCE_THRESHOLD = _POLICY.high_risk_confidence_threshold
MAX_CLARIFICATION_ATTEMPTS = _POLICY.max_clarification_attempts

VAGUE_CONFIDENCE = CONFIDENCE_THRESHOLD - 0.05
CLEAR_CONFIDENCE = min(CONFIDENCE_THRESHOLD + 0.20, 1.0)


def _state(**overrides) -> dict:
    base = {
        "category": "ISSUE",
        "confidence": VAGUE_CONFIDENCE,
        "language_tags": [],
        "clarification_attempts": 0,
    }
    base.update(overrides)
    return base


def test_vague_ticket_clarifies_then_resolves_within_max_attempts():
    """Low confidence -> clarify; once a follow-up clears the bar, ai."""
    result = decide_route(_state(clarification_attempts=0))
    assert result["route"] == "clarify"
    assert result["clarification_attempts"] == 1

    # simulate the customer's reply resolving the ambiguity
    result = decide_route(
        _state(confidence=CLEAR_CONFIDENCE, clarification_attempts=result["clarification_attempts"])
    )
    assert result["route"] == "ai"
    # attempts count carries forward unchanged once resolved
    assert result["clarification_attempts"] == 1


def test_one_clarifying_question_then_an_answer_or_no_guide():
    """Confidence never clears the bar -> ONE clarifying question (the
    default; docs/CHAT_CONTRACT.md rule 5), then route ai: generate_response
    answers from the KB entry that matches, or says there is no guide and
    raises a ticket. Never a bare hand-off, never a second question."""
    assert MAX_CLARIFICATION_ATTEMPTS == 1
    result = decide_route(_state(clarification_attempts=0))
    assert (result["route"], result["clarification_attempts"]) == ("clarify", 1)
    result = decide_route(_state(clarification_attempts=1))
    assert result["route"] == "ai" and "no guide and a ticket" in result["route_reason"]
    assert result["clarification_attempts"] == 1


def test_escalation_tag_overrides_mid_clarification_immediately():
    """An escalation language tag must win immediately, even partway through
    a clarification loop and even though confidence would otherwise clarify
    (not yet at MAX_CLARIFICATION_ATTEMPTS)."""
    result = decide_route(
        _state(
            confidence=CLEAR_CONFIDENCE,  # would otherwise be a clean "ai"
            language_tags=["offensive_language"],
            clarification_attempts=1,
        )
    )
    assert result["route"] == "human"
    assert "escalation language tag" in result["route_reason"]
    # hard override doesn't consume/advance a clarification attempt
    assert result["clarification_attempts"] == 1


def test_high_risk_category_below_high_risk_bar_escalates_immediately_no_clarify():
    """A high-risk category (ACCOUNT/DATA) below the stricter 90% bar must
    skip the clarify loop entirely and escalate straight to a human —
    licensing/billing or data-retention ambiguity is exactly the case
    where an AI shouldn't be probing first, even though this confidence
    clears the base 75% threshold that would let a non-high-risk category
    clarify."""
    confidence = HIGH_RISK_CONFIDENCE_THRESHOLD - 0.05
    assert confidence >= CONFIDENCE_THRESHOLD  # clears base bar, not the high-risk one
    result = decide_route(
        _state(category="ACCOUNT", confidence=confidence, clarification_attempts=0)
    )
    assert result["route"] == "human"
    assert result["clarification_attempts"] == 0


def test_high_risk_ticket_with_nothing_to_clarify_escalates_on_first_call():
    """A low-confidence high-risk-category ticket with no report to pin
    down (no ticket text here) escalates to human on the first call: no
    clarify round, clarification_attempts stays at 0. A vague first report
    gets one clarifying question first (tests/test_live_chat_review.py)."""
    result = decide_route(
        _state(category="DATA", confidence=0.5, clarification_attempts=0)
    )
    assert result["route"] == "human"
    assert "no further clarification for account/billing/data risk" in result["route_reason"]
    assert result["clarification_attempts"] == 0


def test_high_risk_category_stays_immediate_human_even_mid_clarification():
    """If a non-high-risk clarify loop reveals the ticket is actually
    high-risk (e.g. a vague ISSUE ticket turns out to be about a
    DATA retention request) with confidence still below the high-risk
    bar, it must escalate immediately rather than continuing to clarify
    just because clarification_attempts hasn't hit the max yet."""
    result = decide_route(
        _state(
            category="DATA",
            confidence=HIGH_RISK_CONFIDENCE_THRESHOLD - 0.1,
            clarification_attempts=1,
        )
    )
    assert result["route"] == "human"
    # attempts count is left as-is — this isn't a clarify round
    assert result["clarification_attempts"] == 1


def test_clear_confidence_routes_to_ai_without_clarifying():
    result = decide_route(_state(confidence=CLEAR_CONFIDENCE, clarification_attempts=0))
    assert result["route"] == "ai"
    assert result["clarification_attempts"] == 0


def test_admin_routing_settings_change_the_decision(monkeypatch):
    """A saved policy applies to the next decision: with ISSUE marked
    high-risk, a 0.85 ISSUE ticket escalates instead of auto-resolving;
    with negation no longer an escalation tag, it doesn't force a human."""
    state = {"category": "ISSUE", "confidence": 0.85, "language_tags": ["negation"],
             "clarification_attempts": 0}
    assert decide_route(state)["route"] == "human"  # default: negation forces a human

    monkeypatch.setitem(app_settings._overrides, "routing", {
        "escalation_language_tags": ["offensive_language"], "high_risk_categories": ["ISSUE"]})
    assert decide_route(state)["route"] == "human"  # now: high-risk below its 0.90 bar
    assert decide_route({**state, "confidence": 0.95})["route"] == "ai"

    monkeypatch.setitem(app_settings._overrides, "routing", {"escalation_language_tags": []})
    assert decide_route(state)["route"] == "ai"


# ---------------------------------------------------------------------------
# Language tags come from the customer's latest message (chat eval: every
# first report with "not", "isn't" or a long sentence was handed off at once).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("transcript, tags", [
    ("My dashboard isn't working right.", []),                      # a first report: the problem itself
    ("this is useless, nothing works!!! How do I clear the cache?", []),   # frustration is answered
    ("I checked the page and then the logs and also the console but it says nothing at all", []),
    ("Customer: how do I clear the cache?\nAgent (AI): 1. Open settings, not the menu.\n"
     "Customer: I'm not sure which one it is", []),                  # the bot's "not" never counts
    ("Customer: how do I clear the cache?\nAgent (AI): 1. Open settings.\nCustomer: it's still not working",
     ["negation"]),                                                  # the answer failed: a person takes over
    ("what is this shit", ["offensive_language"]),
])
def test_language_tags_come_from_the_latest_customer_message(transcript, tags):
    from backend import graph

    assert graph._detect_language_tags(transcript) == tags


def test_an_off_topic_message_gets_a_brief_fixed_reply_and_never_the_same_question_twice(monkeypatch):
    from backend import graph, topic_terms

    monkeypatch.setitem(app_settings._overrides, "product", {"name": "Brightdesk HR"})
    topic_terms.use([{"label": "Payroll", "kind": "module", "aliases": ["payslip"]}])
    state = {"ticket_text": "who won the cricket match yesterday?", "category": "OTHER", "kb_candidates": []}
    first = graph.off_topic_reply(state)
    assert first == graph.OFF_TOPIC_REPLY.format(product="Brightdesk HR")
    again = graph.off_topic_reply({**state, "ticket_text": f"Customer: who won?\nAgent (AI): {first}\n"
                                                           "Customer: tell me a joke"})
    assert again == graph.OFF_TOPIC_AGAIN.format(product="Brightdesk HR") and "?" not in again
    # A product question is never off-topic, even unclassified or uncovered.
    assert graph.off_topic_reply({**state, "ticket_text": "my payslip is wrong"}) is None
    assert graph.off_topic_reply({**state, "category": "ISSUE"}) is None
    assert graph.off_topic_reply({**state, "kb_candidates": [{"kb_entry_id": "KB-1"}]}) is None
