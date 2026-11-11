"""Confirmed terms' names in the KB search, and hostnames at term review.

- kb_retrieval scores each entry against the query and the query with the
  names of the confirmed terms it names (topic_terms.with_names), keeping
  the better score: a customer writing "Content Security Policy" finds
  the entry whose questions say "CSP". (A long pasted error gains little:
  its other words outweigh the added name.)
- review.unmatched_hostnames: a hostname in the term's evidence section
  that contains its label ("static.widgetrum.com" for "RUM") but that the
  term doesn't match is shown to the reviewer; no hostname matching in code.
"""

from __future__ import annotations

from backend import kb_retrieval, topic_terms
from kb_ingester.review import unmatched_hostnames

ENTRY = {"kb_entry_id": "KB-0001", "title": "Allow the widget under your policy", "category": "SETUP",
         "kind": "troubleshooting", "answer": "The policy must allow the widget's servers.", "steps": [],
         "questions": ["How do I update my CSP to allow the widget?", "What CSP settings does the widget need?"]}
OTHER = {"kb_entry_id": "KB-0002", "title": "Payslip missing", "category": "ISSUE", "kind": "troubleshooting",
         "answer": "Payslips show once payroll has run.", "steps": [],
         "questions": ["Why can't I see my payslip?", "My salary slip is missing"]}
ERROR = ("Refused to load the script 'https://static.widgetrum.com/beacon.js' because it violates the "
         "following Content Security Policy directive: \"script-src ...\"")


def test_a_terms_aliases_join_the_query():
    kb_retrieval.use([ENTRY, OTHER])
    topic_terms.use([])
    message = "Content Security Policy blocks the widget"   # 0.26 as written, 0.45 with "CSP"
    assert kb_retrieval.retrieve_candidates(message) == []
    topic_terms.use([{"label": "Content Security Policy", "kind": "module", "aliases": ["CSP"]}])
    [top] = kb_retrieval.retrieve_candidates(message)
    assert top.entry.kb_entry_id == "KB-0001"
    # The query as written still scores the same: an exact question stays near 1.
    [exact] = kb_retrieval.retrieve_candidates(ENTRY["questions"][0])
    assert exact.score > 0.99


def test_with_names_only_adds_terms_the_text_names():
    topic_terms.use([{"label": "Content Security Policy", "kind": "module", "aliases": ["CSP"]},
                     {"label": "Payroll", "kind": "module", "aliases": []}])
    assert topic_terms.with_names("my csp blocks it") == "my csp blocks it Content Security Policy"
    assert topic_terms.with_names("nothing here") == "nothing here"


def _term(label, aliases=()):
    return {"label": label, "pattern": topic_terms.pattern_for([label, *aliases])}


def test_a_hostname_holding_the_label_but_not_matched_is_shown():
    chunk = "Load https://static.widgetrum.com/beacon.js and send to col.widgetrum.eu or www.example.com."
    assert unmatched_hostnames(_term("RUM"), chunk) == ["static.widgetrum.com", "col.widgetrum.eu"]
    assert unmatched_hostnames(_term("RUM", ["static.widgetrum.com", "col.widgetrum.eu"]), chunk) == []
    assert unmatched_hostnames(_term("Payroll"), chunk) == []
    assert unmatched_hostnames(_term("RUM"), None) == []   # chunk text purged after review
