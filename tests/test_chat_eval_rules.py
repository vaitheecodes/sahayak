"""The chat eval's code rules (backend/evals/rules.py) on hand-written
transcripts: no model calls."""

from __future__ import annotations

from backend.evals import rules

PACK = {"entries": [{
    "kb_entry_id": "KB-0001", "title": "Allow the widget in your policy", "kind": "how-to",
    "questions": ["How do I allow the widget in my CSP?"],
    "answer": "Allow the widget's servers; for Europe use static.widget.eu instead.",
    "steps": [{"text": "Add the policy below to your page."}],
    "snippets": ["<meta content=\"script-src https://static.widget.com\">"]}]}


def _check(kind, turns, expected="answer", entry_id="KB-0001", issue=None):
    case = {"case_id": "c", "kb": "t", "kind": kind, "entry_id": entry_id, "expected": expected}
    result = {"case": case, "issue": issue or turns[0][0], "error": None,
              "turns": [{"customer": c, "bot": b, "status": s, "ticket_id": "TCK-1" if s == "escalated" else None,
                         "ai_error": None} for c, b, s in turns]}
    return {n: v for n, (v, _) in rules.check(result, PACK, "t").items()}


ANSWER = "Allow the widget's servers.\n\n1. Add the policy below to your page."


def test_a_greeting_must_greet_and_never_be_the_problem_text():
    ok = _check("small_talk", [("hi", "Hi! What can I help you with today?", "active"),
                               ("how do i allow the widget in my csp", ANSWER, "active")],
                issue="how do i allow the widget in my csp")
    assert ok[2] == "pass" and ok[3] == "pass"
    bad = _check("small_talk", [("hi", "What are you seeing?", "active"), ("allow the widget?", ANSWER, "active")])
    assert bad[2] == "fail"


def test_a_covered_question_escalated_fails_rule_3_and_invented_values_fail_rule_1():
    v = _check("direct", [("how do i allow the widget?", "Add cdn.other.com to the policy.", "escalated")])
    assert v[3] == "fail" and v[1] == "fail"


def test_ok_closing_the_chat_and_a_contradicting_snippet_fail():
    v = _check("ok_thanks", [("allow the widget?", ANSWER, "active"), ("ok", "Glad it helped.", "resolved")])
    assert v[7] == "fail"
    shown = ("For Europe use static.widget.eu.\n\n```\n<meta content=\"script-src https://static.widget.com\">\n```")
    assert _check("direct", [("widget in europe?", shown, "active")])[10] == "fail"


def test_a_human_request_must_escalate_and_one_question_is_the_limit():
    assert _check("human_request", [("it broke", "Which page?", "active"),
                                     ("I want to talk to a human", "Sure, which page?", "active")],
                  expected="ticket")[13] == "fail"
    v = _check("vague", [("it broke", "Which page is it on?", "active"), ("home", "Which browser is it?", "active")])
    assert v[5] == "fail"


def test_the_original_rules_still_fail_a_hand_off_after_an_answer():
    # rescore.py scores every run both ways: the original rule 3 fails any
    # escalation; the current one only an escalation before the first answer.
    from backend.evals import rescore

    turns = [("how do i allow the widget?", ANSWER, "active"), ("still not working", "Passed to the team.", "escalated")]
    case = {"case_id": "c", "kb": "t", "kind": "direct", "entry_id": "KB-0001", "expected": "answer"}
    result = {"case": case, "issue": turns[0][0], "error": None,
              "turns": [{"customer": c, "bot": b, "status": s, "ticket_id": "T" if s == "escalated" else None,
                         "ai_error": None} for c, b, s in turns]}
    assert rules.check(result, PACK, "t")[3][0] == "pass"
    row = {"result": result, "verdicts": {"1": ["pass", ""]},
           "judge": {"covered": True, "helpful": 4, "tone": 5, "invented": []}}
    assert rescore.original_verdicts(row, PACK, "t")[3][0] == "fail"
