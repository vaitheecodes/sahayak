"""Lightweight KB-candidate retrieval for the live app.

Searches the approved entries of the knowledge base (kb_entries in the
database, backend/kb_store.py), loaded once per process and reloaded after
every KB change, and scores them against incoming ticket text with
TF-IDF-weighted cosine similarity over word tokens. No embedding model is
wired in; this is deliberately simple and dependency-free, but it's enough
to ground classify_ticket's confidence and ask_clarifying_question's
prompt in the product's real support topics instead of asking an LLM to
classify blind against a bare list of category names.

Each question of an entry is one search document, and an entry is one
topic: a search scores every question and returns each entry once, as its
best-matching question, so the top results are distinct topics.
(Near-duplicate entries are flagged when they are drafted, kb_ingester/.)

A best score below KB_MIN_SCORE (default 0.35) is not a match: nothing
is returned, and callers treat that as "no close KB match". A how-to
search (skip_faults) leaves out troubleshooting entries, so "how do I
export the report" isn't answered from "the report export fails".

Sahayak starts with an empty KB: every search returns [] until entries
are approved.
"""

from __future__ import annotations

import logging
import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from backend import request_kind, topic_terms

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Cosine-similarity score above which a top candidate is treated as a
# confident, direct KB match — strong enough to skip clarification and
# resolve straight to generate_response, or to boost classify_ticket's
# raw LLM confidence for a short/common phrasing it under-scored.
STRONG_MATCH_SCORE = 0.40

# Below this a candidate is not a match at all (KB_MIN_SCORE overrides):
# a lone shared word such as "device" or "error" scores around 0.3.
DEFAULT_MIN_SCORE = 0.35


def kb_min_score() -> float:
    raw = os.environ.get("KB_MIN_SCORE", "").strip()
    if not raw:
        return DEFAULT_MIN_SCORE
    try:
        value = float(raw)
    except ValueError:
        logger.warning("KB_MIN_SCORE is not a number; using %.2f", DEFAULT_MIN_SCORE)
        return DEFAULT_MIN_SCORE
    return min(max(value, 0.0), 1.0)

# KB questions are formally phrased ("how do I...", "why is X...");
# real customer messages are casual ("I want...", "can you help...").
# Against a small, stylistically narrow corpus, generic filler words end
# up RARE in the KB text and so get an anomalously high
# document-frequency-based IDF, which lets filler-word overlap outweigh
# real topic words. Stripped before scoring rather than left to IDF, since
# IDF alone isn't reliable at this corpus size. Task verbs ("add", "set"
# up) likewise: one "set up ..." question made "set" outweigh the topic of
# every "how do I set up X".
_STOPWORDS = frozenset(
    """
    i me my myself we our ours ourselves you your yours yourself
    yourselves he him his she her it its they them their this that
    these those am is are was were be been being have has had having
    do does did doing a an the and but if or because as until while
    of at by for with about against between into through during
    before after above below to from up down in out on off over under
    again further then once here there when where why how all any
    both each few more most other some such no nor not only own same
    so than too very s t can will just should now please want wanted
    wants needing need needs needed help helping helped would could
    like get got go going add adding set setup setting yes ok okay thanks thank
    """.split()
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


tokenize = _tokenize  # public: also used for incident lexical similarity


@dataclass(frozen=True)
class KBEntry:
    kb_entry_id: str
    category: str
    intent: str          # the entry's title
    instruction: str     # one of its questions
    response: str        # its answer and numbered steps (kb_store.response_text)
    # "escalate_with_info" entries tell the customer what to collect and
    # hand the case to support (graph.generate_response); `collect` lists
    # those details.
    handling: str = "answer"
    collect: tuple[str, ...] = ()
    # "how-to" or "troubleshooting" (None: guessed from the question's
    # wording, request_kind.is_fault).
    kind: str | None = None
    # The confirmed product terms the entry applies to (topic_terms).
    applies_to: tuple[str, ...] = ()
    source_url: str | None = None
    # Code/config/command lines shown verbatim under an answer, and the
    # source's licence that goes with them.
    snippets: tuple[str, ...] = ()
    source_licence: str | None = None

    @property
    def is_fault(self) -> bool:
        if self.kind:
            return self.kind == "troubleshooting"
        return request_kind.is_fault(self.instruction)


@dataclass(frozen=True)
class KBCandidate:
    entry: KBEntry
    score: float


class _KBIndex:
    def __init__(self, entries: list[KBEntry]):
        self.entries = entries
        self.topics = [e.kb_entry_id for e in entries]
        self._doc_tokens = [_tokenize(e.instruction) for e in entries]
        self._faults = [e.is_fault for e in entries]

        doc_freq: Counter = Counter()
        for tokens in self._doc_tokens:
            doc_freq.update(set(tokens))
        n_docs = max(len(entries), 1)
        self._idf = {
            term: math.log((n_docs + 1) / (count + 1)) + 1.0
            for term, count in doc_freq.items()
        }
        self._doc_vectors = [self._vectorize(tokens) for tokens in self._doc_tokens]
        self._doc_norms = [
            math.sqrt(sum(v * v for v in vec.values())) for vec in self._doc_vectors
        ]

    def _vectorize(self, tokens: list[str]) -> Counter:
        tf = Counter(tokens)
        return Counter({t: c * self._idf.get(t, 1.0) for t, c in tf.items()})

    def search(self, text: str, top_k: int = 3, min_score: float = 0.0,
               category: str | None = None, skip_faults: bool = False) -> list[KBCandidate]:
        """Up to top_k distinct topics scoring at least min_score, each as
        its best-matching entry; only entries of `category` when given;
        no entry whose question reports a fault with skip_faults. Each
        entry's score is the better of the query as written and the query
        with the names of the confirmed terms it names added
        (topic_terms.with_names: "Content Security Policy" finds "CSP")."""
        queries = []
        for query in dict.fromkeys((text, topic_terms.with_names(text))):
            query_vec = self._vectorize(_tokenize(query))
            query_norm = math.sqrt(sum(v * v for v in query_vec.values()))
            if query_norm:
                queries.append((query_vec, query_norm))

        best: dict[str, KBCandidate] = {}
        for entry, topic, doc_vec, doc_norm, fault in zip(
            self.entries, self.topics, self._doc_vectors, self._doc_norms, self._faults
        ):
            if doc_norm == 0 or (category is not None and entry.category != category) or (skip_faults and fault):
                continue
            score = max(sum(w * doc_vec.get(t, 0.0) for t, w in query_vec.items()) / (query_norm * doc_norm)
                        for query_vec, query_norm in queries) if queries else 0.0
            if score > 0 and score >= min_score and (topic not in best or score > best[topic].score):
                best[topic] = KBCandidate(entry=entry, score=score)

        return sorted(best.values(), key=lambda c: c.score, reverse=True)[:top_k]


def build_index(docs: list[dict]) -> "_KBIndex":
    """An index over search documents (kb_store.retrieval_docs)."""
    return _KBIndex([
        KBEntry(kb_entry_id=e["kb_entry_id"], category=e["category"], intent=e["intent"],
                instruction=e["instruction"], response=e["response"] or "",
                handling=e.get("handling") or "answer", collect=tuple(e.get("collect") or ()),
                kind=e.get("kind"), applies_to=tuple(e.get("applies_to") or ()),
                source_url=e.get("source_url"), snippets=tuple(e.get("snippets") or ()),
                source_licence=e.get("source_licence"))
        for e in docs
    ])


_override: list[dict] | None = None


def use(entries: list[dict] | None) -> None:
    """Search these entries (pack format, kb_store) instead of the
    database's approved ones: tests. None goes back to the database."""
    global _override
    _override = [dict(e) for e in entries] if entries is not None else None
    reload()


@lru_cache(maxsize=1)
def _load_index() -> "_KBIndex":
    from backend import db, kb_store

    if _override is not None:
        return build_index(kb_store.retrieval_docs(_override))
    conn = db.get_connection()
    try:
        return build_index(kb_store.retrieval_docs(kb_store.approved_entries(conn)))
    finally:
        conn.close()


def reload() -> None:
    _load_index.cache_clear()


def entry_count() -> int:
    """Approved KB entries the search uses; 0 for an empty or unreadable
    KB. Logged at startup and shown on /api/meta."""
    try:
        index = _load_index()
    except Exception as exc:  # e.g. the database isn't initialised yet
        logger.warning("KB not loaded (%s)", type(exc).__name__)
        return 0
    return len({e.kb_entry_id for e in index.entries})


def retrieve_candidates(ticket_text: str, top_k: int = 3, min_score: float | None = None,
                        category: str | None = None, skip_faults: bool = False) -> list[KBCandidate]:
    """Top-k distinct KB topics (by TF-IDF cosine similarity) for
    `ticket_text`, none scoring below `min_score` (default KB_MIN_SCORE).
    Returns [] for an empty KB or when nothing matches closely enough —
    callers must treat an empty list as "no close KB match": no
    grounding, not an error. `category` limits the search to that
    category's entries; `skip_faults` (a how-to request) leaves out
    troubleshooting entries."""
    floor = kb_min_score() if min_score is None else min_score
    return _load_index().search(ticket_text, top_k=top_k, min_score=floor, category=category,
                                skip_faults=skip_faults)
