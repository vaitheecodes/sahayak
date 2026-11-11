"""The knowledge base in the database: entries, their questions and
quote-backed steps, and the product terms they apply to.

Tables (backend/db.py SCHEMA, migrations/postgres/0003_kb.sql):

  kb_entries          one row per entry: title, answer, kind, handling,
                      category, status (draft / approved / rejected /
                      retired), where it came from (source_url, document,
                      chunk and the chunk's hash when it was drafted),
                      stale / duplicate flags, who reviewed it
  kb_entry_questions  the customer-style questions retrieval matches on
  kb_entry_steps      numbered steps, each with the passage it is backed by
                      (code/config/command snippets: kb_entries.snippets)
  kb_terms            product terms (modules, variants, platforms,
                      integrations, editions) with aliases; only confirmed
                      ones affect grounding (backend/topic_terms.py)
  kb_entry_terms      which terms an entry applies to

Only approved entries are searched (backend/kb_retrieval.py). Every write
here ends with changed(), which drops the process caches of retrieval and
terms (one process: the Procfile runs a single uvicorn worker).

A "pack" is the JSON exchange format: tests/fixtures/kb/brightdesk.json,
scripts/kb_import.py and export_pack(). It carries approved entries and
confirmed terms between environments; drafting from sources is the
ingester's job (kb_ingester/).
"""

from __future__ import annotations

import json
import re

from backend import categories
from backend.timeutil import utcnow

ID_PATTERN = re.compile(r"^KB-\d{4,6}$")
ENTRY_STATUSES = ("draft", "approved", "rejected", "retired")
# "how-to": doing a task; "troubleshooting": fixing a fault; "reference":
# what a table or parameter list says (never grounds a how-to answer). Beats
# the question-wording guess (request_kind) in retrieval.
KINDS = ("how-to", "troubleshooting", "reference")
# "escalate_with_info": the reply lists what support needs, and the
# ticket is raised in the same turn (graph.generate_response).
HANDLING = ("answer", "escalate_with_info")
TERM_KINDS = ("module", "variant", "platform", "integration", "edition")
TERM_STATUSES = ("proposed", "confirmed", "rejected", "merged")
LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ()/+.&'-]{0,40}$")
MAX_QUESTIONS = 10
MAX_STEPS = 40
MAX_COLLECT = 10
MAX_SNIPPETS = 3
MAX_SNIPPET_CHARS = 600


def _now() -> str:
    return utcnow().isoformat()


def changed() -> None:
    """Drop the cached index and terms after a KB write."""
    from backend import kb_retrieval, topic_terms  # lazy: both read from here

    kb_retrieval.reload()
    topic_terms.reload()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _text_list(value, name: str, limit: int, problems: list[str], *, required: bool) -> list[str]:
    if value is None:
        value = []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        problems.append(f"{name} must be a list of text")
        return []
    items = [v.strip() for v in value if v.strip()]
    if required and not items:
        problems.append(f"{name} needs at least one item")
    if len(items) > limit:
        problems.append(f"{name} has more than {limit} items")
    return items


def entry_problems(entry: dict, *, approved: bool, known_terms: set[str]) -> list[str]:
    """What is wrong with an entry (pack format); empty: valid. An entry
    to be approved needs an answer. Messages name fields, never quote the
    entry's text."""
    problems: list[str] = []
    if not isinstance(entry, dict):
        return ["is not an object"]
    if entry.get("kb_entry_id") is not None and not ID_PATTERN.match(str(entry["kb_entry_id"])):
        problems.append("kb_entry_id must look like KB-0001")
    if not str(entry.get("title") or "").strip():
        problems.append("title is required")
    if entry.get("category") not in categories.names():
        problems.append("category is not a confirmed category")
    if entry.get("source_licence") is not None and (not isinstance(entry["source_licence"], str)
                                                    or len(entry["source_licence"]) > 200):
        problems.append("source_licence must be text of at most 200 characters")
    if entry.get("kind") is not None and entry["kind"] not in KINDS:
        problems.append(f"kind must be one of {', '.join(KINDS)}")
    if (entry.get("handling") or "answer") not in HANDLING:
        problems.append(f"handling must be one of {', '.join(HANDLING)}")
    _text_list(entry.get("questions"), "questions", MAX_QUESTIONS, problems, required=True)
    _text_list(entry.get("collect"), "collect", MAX_COLLECT, problems, required=False)
    snippets = _text_list(entry.get("snippets"), "snippets", MAX_SNIPPETS, problems, required=False)
    if any(len(s) > MAX_SNIPPET_CHARS for s in snippets):
        problems.append(f"a snippet is longer than {MAX_SNIPPET_CHARS} characters")
    unknown = [t for t in _text_list(entry.get("applies_to"), "applies_to", 10, problems, required=False)
               if t not in known_terms]
    if unknown:
        problems.append(f"applies_to names {len(unknown)} term(s) that aren't confirmed")
    steps = entry.get("steps") or []
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        problems.append(f"steps must be a list of at most {MAX_STEPS}")
        steps = []
    for i, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or not str(step.get("text") or "").strip():
            problems.append(f"step {i} needs text")
        elif not str(step.get("quote") or "").strip():
            problems.append(f"step {i} needs the passage it is backed by (quote)")
    if approved and not str(entry.get("answer") or "").strip() and not steps and not snippets:
        problems.append("an approved entry needs an answer, steps or snippets")
    return problems


def term_problems(term: dict) -> list[str]:
    from backend import topic_terms

    problems = []
    if not isinstance(term, dict):
        return ["is not an object"]
    if not isinstance(term.get("label"), str) or not LABEL_PATTERN.match(term["label"]):
        problems.append("label must be 1-41 letters, digits, spaces or ()/+.&'-")
    if term.get("kind") not in TERM_KINDS:
        problems.append(f"kind must be one of {', '.join(TERM_KINDS)}")
    aliases = term.get("aliases") or []
    if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
        problems.append("aliases must be a list of non-empty text")
    elif topic_terms.pattern_problem(topic_terms.pattern_for([term.get("label") or "", *aliases])):
        problems.append("aliases make a pattern that matches every message")
    return problems


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------
def _term_ids(conn, *, include_proposed: bool = False) -> dict[str, int]:
    statuses = "('confirmed', 'proposed')" if include_proposed else "('confirmed')"
    return {row["label"]: row["term_id"] for row in conn.execute(
        f"SELECT term_id, label FROM kb_terms WHERE status IN {statuses}")}


def confirmed_terms(conn) -> list[dict]:
    return [{"label": row["label"], "kind": row["kind"], "aliases": json.loads(row["aliases"]),
             "pattern": row["pattern"]}
            for row in conn.execute(
                "SELECT label, kind, aliases, pattern FROM kb_terms WHERE status = 'confirmed' ORDER BY label")]


def save_term(conn, term: dict, *, status: str, actor: str) -> int:
    """Insert a term, or update the one with the same label (any case).
    The caller commits."""
    from backend import topic_terms

    problems = term_problems(term)
    if problems:
        raise ValueError(f"term: {'; '.join(problems)}")
    if status not in TERM_STATUSES:
        raise ValueError(f"Unknown term status {status!r}")
    aliases = sorted({a.strip() for a in term.get("aliases") or []})
    pattern = topic_terms.pattern_for([term["label"], *aliases])
    confirmed = (actor, _now()) if status == "confirmed" else (None, None)
    row = conn.execute("SELECT term_id FROM kb_terms WHERE lower(label) = lower(?)", (term["label"],)).fetchone()
    if row:
        conn.execute(
            "UPDATE kb_terms SET label = ?, kind = ?, aliases = ?, pattern = ?, status = ?, "
            "confirmed_by = ?, confirmed_at = ? WHERE term_id = ?",
            (term["label"], term["kind"], json.dumps(aliases), pattern, status, *confirmed, row["term_id"]),
        )
        return row["term_id"]
    return conn.execute(
        "INSERT INTO kb_terms (label, kind, aliases, pattern, status, evidence_quote, proposed_by, "
        "created_at, confirmed_by, confirmed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING term_id",
        (term["label"], term["kind"], json.dumps(aliases), pattern, status, term.get("evidence_quote"),
         actor, _now(), *confirmed),
    ).fetchone()["term_id"]


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------
def next_entry_id(conn) -> str:
    numbers = [int(row["kb_entry_id"][3:]) for row in conn.execute("SELECT kb_entry_id FROM kb_entries")
               if ID_PATTERN.match(row["kb_entry_id"])]
    return f"KB-{max(numbers, default=0) + 1:04d}"


# Where a drafted entry came from (kb_ingester/runs.py); kept as they are
# when an entry is edited or approved.
DRAFT_FIELDS = ("document_id", "chunk_id", "chunk_hash", "run_id", "duplicate_of", "duplicate_score",
                "draft_notes")


def save_entry(conn, entry: dict, *, status: str, actor: str, draft: dict | None = None) -> str:
    """Insert an entry (pack format), or replace the one with its
    kb_entry_id, with its questions, steps and terms. Raises ValueError
    for an invalid entry. The caller commits, then calls changed().

    A draft may apply to proposed terms too (shown once confirmed); an
    approved entry only to confirmed ones. Steps may carry quote_offset
    and support_check (the ingester's checks). `draft`: DRAFT_FIELDS for
    a new entry from the ingester."""
    if status not in ENTRY_STATUSES:
        raise ValueError(f"Unknown entry status {status!r}")
    term_ids = _term_ids(conn, include_proposed=status == "draft")
    problems = entry_problems(entry, approved=status == "approved", known_terms=set(term_ids))
    if problems:
        raise ValueError(f"{entry.get('kb_entry_id') or 'entry'}: {'; '.join(problems)}")
    entry_id = entry.get("kb_entry_id") or next_entry_id(conn)
    now = _now()
    reviewed = (actor, now) if status in ("approved", "rejected") else (None, None)
    values = (status, entry["title"].strip(), (entry.get("answer") or "").strip(), entry.get("kind"),
              entry.get("handling") or "answer", json.dumps([c.strip() for c in entry.get("collect") or []]),
              entry["category"], entry.get("source_url"), entry.get("source_licence"),
              json.dumps([s.strip() for s in entry.get("snippets") or [] if s.strip()]))
    if conn.execute("SELECT 1 FROM kb_entries WHERE kb_entry_id = ?", (entry_id,)).fetchone():
        conn.execute(
            "UPDATE kb_entries SET status = ?, title = ?, answer = ?, kind = ?, handling = ?, collect = ?, "
            "category = ?, source_url = ?, source_licence = ?, snippets = ?, updated_by = ?, updated_at = ?, reviewed_by = ?, reviewed_at = ?, "
            "version = version + 1 WHERE kb_entry_id = ?",
            (*values, actor, now, *reviewed, entry_id),
        )
        for table in ("kb_entry_questions", "kb_entry_steps", "kb_entry_terms"):
            conn.execute(f"DELETE FROM {table} WHERE entry_id = ?", (entry_id,))
    else:
        draft = {k: v for k, v in (draft or {}).items() if k in DRAFT_FIELDS}
        if isinstance(draft.get("draft_notes"), dict):
            draft["draft_notes"] = json.dumps(draft["draft_notes"])
        columns = "".join(f", {k}" for k in draft)
        conn.execute(
            "INSERT INTO kb_entries (status, title, answer, kind, handling, collect, category, source_url, "
            f"source_licence, snippets, kb_entry_id, created_by, created_at, updated_by, updated_at, reviewed_by, "
            f"reviewed_at{columns}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?{', ?' * len(draft)})",
            (*values, entry_id, actor, now, actor, now, *reviewed, *draft.values()),
        )
    questions = [q.strip() for q in entry["questions"] if q.strip()]
    conn.executemany("INSERT INTO kb_entry_questions (entry_id, ordinal, text) VALUES (?, ?, ?)",
                     [(entry_id, i, q) for i, q in enumerate(questions, start=1)])
    conn.executemany(
        "INSERT INTO kb_entry_steps (entry_id, ordinal, text, quote, quote_offset, support_check) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(entry_id, i, s["text"].strip(), s["quote"].strip(), s.get("quote_offset"), s.get("support_check"))
         for i, s in enumerate(entry.get("steps") or [], start=1)])
    conn.executemany("INSERT INTO kb_entry_terms (entry_id, term_id) VALUES (?, ?)",
                     [(entry_id, term_ids[t]) for t in sorted(set(entry.get("applies_to") or []))])
    return entry_id


def _entries(conn, where: str = "", params: tuple = ()) -> list[dict]:
    """Entries in pack format (with status), ordered by id."""
    rows = conn.execute(f"SELECT * FROM kb_entries {where} ORDER BY kb_entry_id", params).fetchall()
    if not rows:
        return []
    questions: dict[str, list[str]] = {}
    for row in conn.execute("SELECT entry_id, text FROM kb_entry_questions ORDER BY entry_id, ordinal"):
        questions.setdefault(row["entry_id"], []).append(row["text"])
    steps: dict[str, list[dict]] = {}
    for row in conn.execute("SELECT entry_id, text, quote FROM kb_entry_steps ORDER BY entry_id, ordinal"):
        steps.setdefault(row["entry_id"], []).append({"text": row["text"], "quote": row["quote"]})
    terms: dict[str, list[str]] = {}
    for row in conn.execute(
            "SELECT et.entry_id, t.label FROM kb_entry_terms et JOIN kb_terms t ON t.term_id = et.term_id "
            "WHERE t.status = 'confirmed' ORDER BY t.label"):
        terms.setdefault(row["entry_id"], []).append(row["label"])
    return [{
        "kb_entry_id": row["kb_entry_id"], "status": row["status"], "title": row["title"],
        "category": row["category"], "kind": row["kind"], "handling": row["handling"],
        "collect": json.loads(row["collect"]), "questions": questions.get(row["kb_entry_id"], []),
        "answer": row["answer"], "steps": steps.get(row["kb_entry_id"], []),
        "applies_to": terms.get(row["kb_entry_id"], []), "source_url": row["source_url"],
        **({"source_licence": row["source_licence"]} if row["source_licence"] else {}),
        **({"snippets": json.loads(row["snippets"])} if json.loads(row["snippets"] or "[]") else {}),
    } for row in rows]


def approved_entries(conn) -> list[dict]:
    return _entries(conn, "WHERE status = 'approved'")


def response_text(entry: dict) -> str:
    """The answer with its steps numbered under it, then its snippets:
    what grounds a reply."""
    steps = [s["text"].strip() for s in entry.get("steps") or [] if s.get("text", "").strip()]
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1))
    snippets = "\n".join(entry.get("snippets") or [])
    return "\n".join(part for part in ((entry.get("answer") or "").strip(), numbered, snippets) if part)


def retrieval_docs(entries: list[dict]) -> list[dict]:
    """One search document per question of each entry (backend/kb_retrieval.py)."""
    return [{
        "kb_entry_id": e["kb_entry_id"], "category": e["category"], "intent": e["title"],
        "instruction": q, "response": response_text(e), "handling": e.get("handling") or "answer",
        "collect": list(e.get("collect") or []), "kind": e.get("kind"),
        "applies_to": list(e.get("applies_to") or []), "source_url": e.get("source_url"),
        "snippets": list(e.get("snippets") or []), "source_licence": e.get("source_licence"),
    } for e in entries for q in e["questions"]]


def count_approved(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM kb_entries WHERE status = 'approved'").fetchone()[0]


# ---------------------------------------------------------------------------
# Packs
# ---------------------------------------------------------------------------
def import_pack(conn, pack: dict, actor: str) -> dict:
    """Confirmed terms and approved entries from a pack, in one
    transaction (nothing is written if any of it is invalid). The product
    profile in a pack is not applied: that is the admin's setting."""
    if not isinstance(pack, dict) or not isinstance(pack.get("entries"), list):
        raise ValueError("A pack is an object with an entries list")
    terms = pack.get("terms") or []
    for term in terms:
        save_term(conn, term, status="confirmed", actor=actor)
    ids = [save_entry(conn, entry, status="approved", actor=actor) for entry in pack["entries"]]
    return {"terms": len(terms), "entries": len(ids)}


def export_pack(conn) -> dict:
    """Approved entries and confirmed terms, in pack format."""
    return {
        "terms": [{k: t[k] for k in ("label", "kind", "aliases")} for t in confirmed_terms(conn)],
        "entries": [{k: v for k, v in e.items() if k != "status"} for e in approved_entries(conn)],
    }
