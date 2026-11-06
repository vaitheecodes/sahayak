"""backend/topic_terms.py: product terms learned from the content.

No term is built in: with none confirmed nothing counts as "specific".
A term's pattern is built from its label and aliases (whole words, any
spacing or hyphen inside an alias, an optional plural). An entry applies
to its reviewed terms; one about another term of the same kind than the
customer named (the Android guide for an iPad) is skipped.
"""

from __future__ import annotations

import pytest

from backend import topic_terms
from tests import kb_fixture


def test_no_terms_are_built_in():
    assert topic_terms.known_terms() == [] and topic_terms.mentioned("pagerduty on android") == set()
    assert topic_terms.missing_terms({"applies_to": ["Android"]}, "anything") == set()


@pytest.mark.parametrize("aliases, text, matches", [
    (["time off"], "I need time off", True),
    (["time off"], "I need time-off", True),
    (["time off"], "I need timeoff", True),
    (["payslip"], "two payslips are missing", True),
    (["ios"], "my bios settings", False),
    (["clock-in"], "clock in fails", True),
])
def test_patterns_match_aliases_as_whole_words(aliases, text, matches):
    topic_terms.use([{"label": "X", "kind": "module", "aliases": aliases}])
    assert (topic_terms.mentioned(text) == {"X"}) is matches


@pytest.mark.parametrize("pattern", ["", "   ", "(", r"\b(?:)?\b|.*"])
def test_unusable_patterns_are_refused(pattern):
    assert topic_terms.pattern_problem(pattern)


def test_kinds_say_which_terms_are_parts_of_the_product():
    kb_fixture.load()
    assert topic_terms.subject_labels() == ["Attendance", "Expenses", "Leave", "Payroll"]
    assert topic_terms.subjects_mentioned("my payslip on android") == ["Payroll"]


@pytest.mark.parametrize("applies_to, text, missing, another", [
    (["Android"], "install the app", {"Android"}, False),
    (["Android"], "install the app on android", set(), False),
    (["Android"], "install the app on my ipad", {"Android"}, True),
    (["Leave"], "my payslip is missing", {"Leave"}, True),
    (["Slack"], "approvals are not posted", {"Slack"}, False),
    ([], "anything", set(), False),
])
def test_missing_terms_and_other_variants(applies_to, text, missing, another):
    kb_fixture.load()
    candidate = {"applies_to": applies_to}
    assert topic_terms.missing_terms(candidate, text) == missing
    assert topic_terms.names_another_variant(candidate, text) is another
