"""backend/kb_retrieval.py: KB-candidate retrieval, and graph.py's use of it.

- Short, casual phrasings ground on a real KB match; filler words don't
  dominate; a weak best match (below KB_MIN_SCORE) is no match.
- Only the customer's own words feed retrieval, never the AI's.
- Each entry is one topic: its questions are phrasings of it, so the top
  results are distinct entries.
- The KB starts empty, and the app searches the database's approved
  entries (kb_store), reloaded after a change.

On the neutral test KB (tests/kb_fixture.py, the fictional Brightdesk HR).
No LLM/network calls.
"""

from __future__ import annotations

import pytest

from backend import db, kb_retrieval, kb_store
from backend.graph import _customer_authored_text, retrieve_kb_candidates
from tests import kb_fixture


@pytest.fixture()
def kb():
    kb_fixture.load()


# ---------------------------------------------------------------------------
# Grounding short or casual phrasings
# ---------------------------------------------------------------------------
def test_short_casual_phrasing_matches_confidently(kb):
    candidates = kb_retrieval.retrieve_candidates("help me with leave", top_k=3)
    assert candidates
    top = candidates[0]
    assert (top.entry.kb_entry_id, top.entry.category, top.entry.intent) == ("KB-0001", "USAGE", "Apply for leave")
    assert top.score >= kb_retrieval.STRONG_MATCH_SCORE


def test_exact_phrasing_scores_near_one(kb):
    candidates = kb_retrieval.retrieve_candidates("How do I apply for leave?", top_k=1)
    assert candidates and candidates[0].score > 0.9


def test_out_of_domain_query_returns_no_strong_match(kb):
    candidates = kb_retrieval.retrieve_candidates("refund my order please", top_k=3)
    assert not any(c.score >= kb_retrieval.STRONG_MATCH_SCORE for c in candidates)


def test_filler_words_do_not_dominate_scoring(kb):
    """Generic filler words ("want", "help") are rare in formally phrased
    KB questions, so their IDF is anomalously high unless stripped."""
    candidates = kb_retrieval.retrieve_candidates("I want you to help me with my leave\ni want to apply", top_k=1)
    assert candidates and candidates[0].entry.kb_entry_id == "KB-0001"


def test_empty_query_returns_no_candidates(kb):
    assert kb_retrieval.retrieve_candidates("", top_k=3) == []


def test_results_carry_what_grounding_needs(kb):
    (top,) = kb_retrieval.retrieve_candidates("can't see my salary slip", top_k=1)
    assert top.entry.kind == "troubleshooting" and top.entry.applies_to == ("Payroll",)
    assert top.entry.source_url == "https://help.example.com/brightdesk/payroll/payslips"
    # The answer and its numbered steps, as the reply is grounded on them.
    assert top.entry.response.splitlines()[-2:] == [
        "1. Open Payroll, then Payslips.", "2. Set the year filter to the current year."]


# ---------------------------------------------------------------------------
# Only customer-authored transcript lines feed retrieval
# ---------------------------------------------------------------------------
def test_customer_authored_text_extracts_only_customer_lines():
    transcript = (
        "Customer: I want you to help me with leave\n"
        "Agent (AI): Are you asking about contacting support or using the feature?\n"
        "Customer: i want to apply"
    )
    extracted = _customer_authored_text(transcript)
    assert "Agent (AI)" not in extracted
    assert "help me with leave" in extracted and "i want to apply" in extracted


def test_customer_authored_text_passes_through_plain_ticket_text():
    plain = "I want you to help me with leave"
    assert _customer_authored_text(plain) == plain


def test_full_transcript_retrieval_beats_ai_noise(kb):
    """Two rounds of the AI's own (generic) clarifying questions don't pull
    retrieval away from what the customer asked."""
    transcript = (
        "Customer: I want you to help me with leave\n"
        "Agent (AI): Do you want to connect Slack or change your plan?\n"
        "Customer: i want to apply\n"
        "Agent (AI): Do you mean the subscription plan?\n"
        "Customer: no, a vacation day"
    )
    candidates = kb_retrieval.retrieve_candidates(_customer_authored_text(transcript), top_k=3)
    assert candidates[0].entry.kb_entry_id == "KB-0001"
    assert not {c.entry.kb_entry_id for c in candidates} & {"KB-0010"}


def test_customer_text_keeps_multi_line_messages_and_drops_ai_steps():
    transcript = (
        "Customer: my payslip is missing\n"
        "but payroll was published\n"
        "Agent (AI): Try these steps:\n"
        "1. Check the year filter.\n"
        "Customer: still missing\n"
        "staff: Looking into it.\n"
    )
    assert _customer_authored_text(transcript) == (
        "my payslip is missing\nbut payroll was published\nstill missing")


# ---------------------------------------------------------------------------
# One topic per entry
# ---------------------------------------------------------------------------
def test_each_entry_is_one_topic_and_results_are_distinct_entries(kb):
    index = kb_retrieval._load_index()
    assert len(index.entries) == sum(len(e["questions"]) for e in kb_fixture.pack()["entries"])
    assert len(set(index.topics)) == len(kb_fixture.pack()["entries"])
    for query in ("install the app", "my payslip is missing", "export a report", "clock in error"):
        hits = kb_retrieval.retrieve_candidates(query, top_k=3, min_score=0)
        ids = [h.entry.kb_entry_id for h in hits]
        assert len(ids) == len(set(ids)), query


def test_the_best_matching_question_represents_its_entry(kb):
    (top,) = kb_retrieval.retrieve_candidates("where can I download the app for ipad", top_k=1)
    assert top.entry.kb_entry_id == "KB-0003" and top.entry.instruction == "where can I download the app for ipad"


# ---------------------------------------------------------------------------
# KB_MIN_SCORE: a weak best match is "no close match"
# ---------------------------------------------------------------------------
WEAK = "I see unable to connect to device error"


def test_weak_match_is_no_match_by_default(kb, monkeypatch):
    monkeypatch.delenv("KB_MIN_SCORE", raising=False)
    weak = kb_retrieval.retrieve_candidates(WEAK, min_score=0)
    assert weak and weak[0].score < kb_retrieval.DEFAULT_MIN_SCORE == 0.35
    assert kb_retrieval.retrieve_candidates(WEAK) == []


def test_min_score_is_configurable(kb, monkeypatch):
    monkeypatch.setenv("KB_MIN_SCORE", "0.2")
    assert kb_retrieval.retrieve_candidates(WEAK)
    monkeypatch.setenv("KB_MIN_SCORE", "0.99")
    assert kb_retrieval.retrieve_candidates("How do I apply for leave?") != []  # exact: 1.0
    assert kb_retrieval.retrieve_candidates("my leave application shows wrong dates") == []


@pytest.mark.parametrize("raw, expected", [("", 0.35), ("abc", 0.35), ("0.5", 0.5), ("-1", 0.0), ("7", 1.0)])
def test_min_score_setting_is_parsed_safely(monkeypatch, raw, expected):
    monkeypatch.setenv("KB_MIN_SCORE", raw)
    assert kb_retrieval.kb_min_score() == expected


def test_no_close_match_reaches_the_pipeline_as_no_candidates(kb, monkeypatch):
    monkeypatch.delenv("KB_MIN_SCORE", raising=False)
    assert retrieve_kb_candidates({"ticket_text": f"Customer: {WEAK}"}) == {"kb_candidates": []}


# ---------------------------------------------------------------------------
# Empty KB, and the database path
# ---------------------------------------------------------------------------
def test_an_empty_kb_matches_nothing():
    assert kb_retrieval.entry_count() == 0
    assert kb_retrieval.retrieve_candidates("How do I apply for leave?", min_score=0) == []


def test_the_app_searches_the_databases_approved_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "kb.db")
    db.init_db()
    kb_retrieval.use(None)  # the database, as the app runs
    assert kb_retrieval.entry_count() == 0
    conn = db.get_connection()
    try:
        kb_store.import_pack(conn, kb_fixture.pack(), "test")
        draft = {**kb_fixture.entry("KB-0001"), "kb_entry_id": None, "title": "Cancel a leave request",
                 "questions": ["how do I cancel my leave request"]}
        kb_store.save_entry(conn, draft, status="draft", actor="test")
        conn.commit()
    finally:
        conn.close()
    kb_store.changed()
    assert kb_retrieval.entry_count() == 10  # approved only: the draft is never searched
    (top,) = kb_retrieval.retrieve_candidates("how do I cancel my leave request", top_k=1)
    assert top.entry.kb_entry_id == "KB-0001"


def test_a_weak_match_is_searched_again_in_the_kbs_own_words(monkeypatch):
    # Chat eval: "update my browser's stored pages" never reached the clear-cache guide.
    from backend import graph
    from backend.ai_service import rewrite_query

    kb_retrieval.use([{"kb_entry_id": "KB-1", "title": "Clear cached pages", "category": "USAGE", "kind": "how-to",
                       "questions": ["How do I clear cached data?", "empty the cache to load the latest version"],
                       "answer": "Clearing the cache loads the latest version.", "steps": []}])
    seen = []
    monkeypatch.setattr(rewrite_query, "rewrite_query",
                        lambda message, topics: seen.append((message, topics)) or "clear cached data")
    state = {"ticket_text": "How can I update my browser's stored pages?"}
    result = graph.retrieve_kb_candidates(state)
    assert [c["kb_entry_id"] for c in result["kb_candidates"]] == ["KB-1"]
    assert seen[0][1] == ["Clear cached pages"] and result["query_rewrite"] == "clear cached data"
    usable, _ = graph.grounding_candidates({**state, **result})
    assert [c["kb_entry_id"] for c in usable] == ["KB-1"]        # the rewrite counts for the subject check

    monkeypatch.setattr(rewrite_query, "rewrite_query", lambda message, topics: "")   # no topic: still nothing
    assert graph.retrieve_kb_candidates(state)["kb_candidates"] == []


def test_a_weak_wrong_match_is_also_searched_again_and_the_better_one_kept(monkeypatch):
    # Chat eval trace: a 0.356 match to the CSP entry stopped the rewrite; the clear-cache guide was 0.28.
    from backend import graph
    from backend.ai_service import rewrite_query

    kb_retrieval.use([
        {"kb_entry_id": "KB-1", "title": "Clear cached data", "category": "USAGE", "kind": "how-to",
         "questions": ["How do I clear cached data?"], "answer": "Clearing the cache loads the latest version.",
         "steps": []},
        {"kb_entry_id": "KB-2", "title": "Update the policy", "category": "ISSUE", "kind": "how-to",
         "questions": ["update policy header"], "answer": "Update the policy.", "steps": []},   # scores 0.36
    ])
    state = {"ticket_text": "How can I update my browser's stored pages?"}
    monkeypatch.setattr(rewrite_query, "rewrite_query", lambda message, topics: "")
    weak = graph.retrieve_kb_candidates(state)["kb_candidates"]
    assert weak and weak[0]["kb_entry_id"] == "KB-2" and weak[0]["score"] < kb_retrieval.STRONG_MATCH_SCORE
    monkeypatch.setattr(rewrite_query, "rewrite_query", lambda message, topics: "clear cached data")
    result = graph.retrieve_kb_candidates(state)
    assert result["kb_candidates"][0]["kb_entry_id"] == "KB-1" and result["query_rewrite"] == "clear cached data"
