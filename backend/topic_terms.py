"""Product terms: which ones a customer has actually mentioned, and which
ones a KB entry applies to.

A term is a module, variant, platform, integration or edition of the
product ("Payroll", "Android", "Slack"), learned from the product's own
content and confirmed by a reviewer (kb_terms, backend/kb_store.py). No
term is built in: Sahayak doesn't know the product in advance.

A KB entry about one of them only applies if the customer has said so.
Retrieval alone can't tell: "I get an error exporting the report" can
match an entry about one integration on "error" and "report".
`missing_terms` flags such an entry so the answer isn't grounded on it as
if it applied (backend/graph.py `grounding_candidates`). An entry's terms
are its reviewed `applies_to` list; customer terms come from the
customer's own words only.

Loaded from the database once per process (reload() after a change);
use() replaces the terms for a test.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

# Kinds that say which part of the product a request is about: the
# clarifying question asks for one when none is named.
SUBJECT_KINDS = ("module", "variant")

_override: list[dict] | None = None


def pattern_for(aliases: list[str]) -> str:
    """A case-insensitive pattern for a term's label and aliases: whole
    words, any spacing or hyphen between the words of an alias, an
    optional plural s."""
    parts = []
    for alias in sorted({a.strip().lower() for a in aliases if a and a.strip()}, key=len, reverse=True):
        words = [re.escape(w) for w in re.split(r"[\s-]+", alias) if w]
        if words:
            parts.append(r"[\s-]?".join(words))
    return rf"\b(?:{'|'.join(parts)})s?\b" if parts else ""


def pattern_problem(pattern) -> str | None:
    """Why `pattern` can't be a term's pattern (None: it can)."""
    if not isinstance(pattern, str) or not pattern.strip():
        return "is empty"
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return "is not a valid regex"
    if compiled.search(""):
        return "matches an empty message, so it would match every message"
    return None


def use(terms: list[dict] | None) -> None:
    """Replace the confirmed terms ({label, kind, aliases}) for a test;
    None goes back to the database."""
    global _override
    _override = [dict(t) for t in terms] if terms is not None else None
    reload()


def _load() -> list[dict]:
    if _override is not None:
        return _override
    from backend import db, kb_store

    try:
        conn = db.get_connection()
    except Exception:  # no database configured (pure-function use)
        return []
    try:
        return kb_store.confirmed_terms(conn)
    except Exception as exc:  # table missing on a database not yet initialised
        logger.warning("Product terms not loaded (%s)", type(exc).__name__)
        return []
    finally:
        conn.close()


@lru_cache(maxsize=1)
def _terms() -> dict[str, tuple[str, re.Pattern]]:
    """label -> (kind, compiled pattern) of every confirmed term."""
    out = {}
    for term in _load():
        pattern = term.get("pattern") or pattern_for([term["label"], *term.get("aliases", [])])
        if pattern_problem(pattern):
            logger.warning("Term %s has an unusable pattern; ignored", term["label"])
            continue
        out[term["label"]] = (term["kind"], re.compile(pattern, re.IGNORECASE))
    return out


@lru_cache(maxsize=1)
def _names() -> dict[str, list[str]]:
    """label -> the label and aliases of every confirmed term."""
    return {t["label"]: [t["label"], *t.get("aliases", [])] for t in _load()}


def with_names(text: str) -> str:
    """`text` followed by the other names (label, aliases) of each
    confirmed term it names: an extra KB query (backend/kb_retrieval.py),
    so "Content Security Policy" finds a question that says "CSP" and back."""
    names = _names()
    extra = [n for label in sorted(mentioned(text)) for n in names.get(label, [label])
             if not re.search(pattern_for([n]), text, re.IGNORECASE)]
    return " ".join([text, *extra])


def reload() -> None:
    _terms.cache_clear()
    _names.cache_clear()


def known_terms() -> list[str]:
    return sorted(_terms())


def kind_of(label: str) -> str | None:
    found = _terms().get(label)
    return found[0] if found else None


def mentioned(text: str) -> set[str]:
    """Every confirmed term named in `text`."""
    return {label for label, (_, pattern) in _terms().items() if pattern.search(text or "")}


def subject_labels() -> list[str]:
    """The modules and variants of the product, for "which part is it?"."""
    return sorted(label for label, (kind, _) in _terms().items() if kind in SUBJECT_KINDS)


def labels_of_kind(kind: str) -> list[str]:
    """Every confirmed term of one kind (the platforms: Android, iOS)."""
    return sorted(label for label, (k, _) in _terms().items() if k == kind)


def subjects_mentioned(customer_text: str) -> list[str]:
    """The modules and variants the customer has named."""
    return sorted(label for label in mentioned(customer_text) if kind_of(label) in SUBJECT_KINDS)


def entry_terms(candidate: dict) -> set[str]:
    """What a KB entry applies to (empty: a generic entry)."""
    return set(candidate.get("applies_to") or ()) & set(_terms())


def missing_terms(candidate: dict, customer_text: str) -> set[str]:
    """The terms of a KB candidate when the customer has mentioned none
    of them; empty when the entry is generic or the customer has named at
    least one."""
    terms = entry_terms(candidate)
    if not terms or terms & mentioned(customer_text):
        return set()
    return terms


def names_another_variant(candidate: dict, customer_text: str) -> bool:
    """The entry applies to a different term than the one the customer
    named, of the same kind: the Android guide for "my iPad app", the
    Payroll entry for a Leave question. Such an entry is neither grounding
    nor worth asking about."""
    named = mentioned(customer_text)
    named_kinds = {kind_of(label) for label in named}
    return any(term not in named and kind_of(term) in named_kinds for term in entry_terms(candidate)) \
        and not entry_terms(candidate) & named
