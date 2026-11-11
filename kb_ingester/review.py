"""The reviewer's side of the KB: drafts, terms and categories.

Who may do what is checked by the API (api.py); everything here assumes
the caller is allowed. Every change is written to audit_events (ids,
statuses and field names only). Functions take an open connection; the
caller commits, then calls kb_store.changed() where retrieval or terms
may have changed.

- A draft can be edited (title, category, kind, questions, answer,
  steps, applies_to) while it is a draft; each edit names the version it
  was made on, so two reviewers can't overwrite each other. A step's
  quote must still be a passage of the chunk while the chunk text is
  kept; a step whose text or quote changed loses its model support check.
- An entry that rewrites a numbered list of N steps but has fewer is
  flagged "incomplete" (X of N); approving it needs acknowledge_incomplete.
- Approving runs the same validation as an import (an approved entry may
  only apply to confirmed terms). Approved and rejected entries are no
  longer editable here.
- Terms: proposed ones are confirmed, rejected, or merged into a
  confirmed term (their label and aliases become its aliases, and
  entries that applied to them apply to it). Only confirmed terms change
  grounding.
- Categories: proposed ones are confirmed, rejected or merged into a
  confirmed one; drafts that asked for one move to it when it is
  confirmed (or to the category it was merged into).
"""

from __future__ import annotations

import json

from backend import audit, categories, kb_store
from backend.timeutil import utcnow
from kb_ingester import checks
from kb_ingester.runs import purge_chunks, staff_name

EDITABLE = ("title", "category", "kind", "questions", "answer", "steps", "snippets", "applies_to")


class ReviewError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return utcnow().isoformat()


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------
def completeness(notes: dict, step_count: int) -> dict | None:
    """{"kept": X, "expected": N} when the entry rewrites a numbered list of
    N steps and has fewer than N now; else None."""
    expected = notes.get("procedure_steps")
    if expected and step_count < expected:
        return {"kept": step_count, "expected": expected}
    return None


def _flags(row: dict, notes: dict, step_count: int | None = None) -> list[str]:
    flags = []
    if step_count is not None and completeness(notes, step_count):
        flags.append("incomplete")
    if row.get("duplicate_of"):
        flags.append("duplicate")
    if row.get("stale"):
        flags.append("stale")
    if row.get("flagged_injection") or notes.get("chunk_signals") or notes.get("output_signals"):
        flags.append("injection")
    if notes.get("removed"):
        flags.append("answer_removed")
    return flags


_LIST_SQL = (
    "SELECT e.kb_entry_id, e.status, e.title, e.category, e.kind, e.source_url, e.stale, e.duplicate_of, "
    "e.duplicate_score, e.draft_notes, e.created_at, e.updated_at, e.version, e.reviewed_by, c.flagged_injection, "
    "s.name AS source_name, s.source_id, "
    "(SELECT COUNT(*) FROM kb_entry_steps st WHERE st.entry_id = e.kb_entry_id) AS step_count, "
    "(SELECT COUNT(*) FROM kb_entry_questions q WHERE q.entry_id = e.kb_entry_id) AS question_count "
    "FROM kb_entries e LEFT JOIN kb_chunks c ON c.chunk_id = e.chunk_id "
    "LEFT JOIN kb_documents d ON d.document_id = e.document_id LEFT JOIN kb_sources s ON s.source_id = d.source_id"
)


def list_entries(conn, *, status: str | None = "draft", flag: str | None = None, source_id: int | None = None,
                 limit: int = 200) -> list[dict]:
    where, params = [], []
    if status and status != "all":
        where.append("e.status = ?")
        params.append(status)
    if source_id:
        where.append("s.source_id = ?")
        params.append(source_id)
    sql = _LIST_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY e.kb_entry_id DESC"
    out = []
    for row in conn.execute(sql, params):
        row = dict(row)
        notes = json.loads(row.pop("draft_notes") or "{}")
        row["flags"] = _flags(row, notes, row["step_count"])
        row["completeness"] = completeness(notes, row["step_count"])
        row.pop("flagged_injection")
        if flag and flag not in row["flags"]:
            continue
        out.append(row)
    return out[:limit]


def _row(conn, entry_id: str) -> dict:
    row = conn.execute("SELECT * FROM kb_entries WHERE kb_entry_id = ?", (entry_id,)).fetchone()
    if row is None:
        raise ReviewError("No such entry", 404)
    return dict(row)


def _pack(conn, entry_id: str) -> dict:
    """The entry in pack format, with steps' check fields and every term
    (proposed ones too) it applies to."""
    entry = kb_store._entries(conn, "WHERE kb_entry_id = ?", (entry_id,))[0]
    entry.setdefault("snippets", [])
    entry["steps"] = [dict(r) for r in conn.execute(
        "SELECT text, quote, quote_offset, support_check FROM kb_entry_steps WHERE entry_id = ? ORDER BY ordinal",
        (entry_id,))]
    entry["applies_to"] = [r["label"] for r in conn.execute(
        "SELECT t.label FROM kb_entry_terms et JOIN kb_terms t ON t.term_id = et.term_id "
        "WHERE et.entry_id = ? AND t.status IN ('confirmed', 'proposed') ORDER BY t.label", (entry_id,))]
    return entry


def entry_detail(conn, entry_id: str) -> dict:
    row = _row(conn, entry_id)
    entry = _pack(conn, entry_id)
    notes = json.loads(row.get("draft_notes") or "{}")
    chunk = None
    if row.get("chunk_id"):
        c = conn.execute("SELECT chunk_id, heading_path, text, flagged_injection, purged_at FROM kb_chunks "
                         "WHERE chunk_id = ?", (row["chunk_id"],)).fetchone()
        chunk = dict(c) if c else None
    source = None
    if row.get("document_id"):
        s = conn.execute("SELECT s.source_id, s.kind, s.config, s.name, s.public_confirmed_by, s.public_confirmed_at, "
                         "s.licence_note, d.url, d.title "
                         "FROM kb_documents d JOIN kb_sources s ON s.source_id = d.source_id WHERE d.document_id = ?",
                         (row["document_id"],)).fetchone()
        source = dict(s) if s else None
        if source:
            source["public_confirmed_by_name"] = staff_name(conn, source["public_confirmed_by"])
            source["filename"] = json.loads(source.pop("config") or "{}").get("filename")
    duplicate = None
    if row.get("duplicate_of"):
        d = conn.execute("SELECT kb_entry_id, title, status FROM kb_entries WHERE kb_entry_id = ?",
                         (row["duplicate_of"],)).fetchone()
        duplicate = {**dict(d), "score": row["duplicate_score"]} if d else None
    terms = [dict(r) for r in conn.execute(
        "SELECT t.label, t.kind, t.status FROM kb_entry_terms et JOIN kb_terms t ON t.term_id = et.term_id "
        "WHERE et.entry_id = ? ORDER BY t.label", (entry_id,))]
    return {
        **entry, "version": row["version"], "stale": bool(row["stale"]), "run_id": row["run_id"],
        "created_by": row["created_by"], "created_at": row["created_at"], "updated_by": row["updated_by"],
        "updated_at": row["updated_at"], "reviewed_by": row["reviewed_by"],
        "reviewed_by_name": staff_name(conn, row["reviewed_by"]), "updated_by_name": staff_name(conn, row["updated_by"]),
        "reviewed_at": row["reviewed_at"],
        "review_note": row["review_note"], "notes": notes, "flags": _flags({**row, **(chunk or {})}, notes, len(entry["steps"])),
        "completeness": completeness(notes, len(entry["steps"])),
        "chunk": chunk, "source": source, "duplicate": duplicate, "terms": terms,
    }


def _check_version(row: dict, version: int) -> None:
    if row["status"] != "draft":
        raise ReviewError("Only a draft can be changed here", 409)
    if version != row["version"]:
        raise ReviewError("Someone else changed this entry; reload it", 409)


def update_draft(conn, entry_id: str, changes: dict, *, version: int, actor: str) -> list[str]:
    """Returns the names of the fields that changed."""
    row = _row(conn, entry_id)
    _check_version(row, version)
    current = _pack(conn, entry_id)
    changed = [f for f in EDITABLE if f in changes and changes[f] != current.get(f)]
    if not changed:
        return []
    entry = {**current, **{f: changes[f] for f in changed}}
    chunk = conn.execute("SELECT text FROM kb_chunks WHERE chunk_id = ?", (row["chunk_id"],)).fetchone() \
        if row.get("chunk_id") else None
    if "steps" in changed:
        steps = entry["steps"]
        if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
            raise ReviewError("steps must be a list of {text, quote}")
        before = {(s["text"], s["quote"]): s for s in current["steps"]}
        checked = []
        for i, step in enumerate(steps, start=1):
            text, quote = str(step.get("text") or "").strip(), str(step.get("quote") or "").strip()
            unchanged_quote = any(s["quote"] == quote for s in current["steps"])
            if chunk and chunk["text"] and not unchanged_quote and checks.quote_problem(quote, chunk["text"]):
                raise ReviewError(f"Step {i}: the quote must be a passage of the source section "
                                  f"({checks.quote_problem(quote, chunk['text'])})")
            old = before.get((text, quote))
            checked.append({"text": text, "quote": quote,
                            "quote_offset": checks.quote_offset(quote, chunk["text"]) if chunk and chunk["text"] else None,
                            "support_check": old["support_check"] if old else None})
        entry["steps"] = checked
    if "snippets" in changed:
        snippets = entry["snippets"]
        if not isinstance(snippets, list) or not all(isinstance(s, str) for s in snippets):
            raise ReviewError("snippets must be a list of text")
        for i, snippet in enumerate(snippets, start=1):
            problem = None if snippet in current["snippets"] or not (chunk and chunk["text"]) \
                else checks.snippet_problem(snippet, chunk["text"])
            if problem:
                raise ReviewError(f"Snippet {i} must be code copied from the source section ({problem})")
    try:
        kb_store.save_entry(conn, entry, status="draft", actor=actor)
    except ValueError as exc:
        raise ReviewError(str(exc)) from None
    audit.record(conn, actor, "kb.entry.update", "kb_entry", entry_id, fields=changed)
    return changed


def _purge_if_decided(conn, row: dict) -> None:
    if row.get("chunk_id"):
        purge_chunks(conn)


def approve(conn, entry_id: str, *, version: int, actor: str, note: str = "",
            acknowledge_incomplete: bool = False) -> None:
    """An entry with fewer steps than the numbered list it rewrites is
    approved only with acknowledge_incomplete (the reviewer checked that
    the missing steps aren't needed)."""
    row = _row(conn, entry_id)
    _check_version(row, version)
    entry = _pack(conn, entry_id)
    notes = json.loads(row.get("draft_notes") or "{}")
    gap = completeness(notes, len(entry["steps"]))
    if gap and not acknowledge_incomplete:
        raise ReviewError(f"Possibly incomplete: {gap['kept']} of {gap['expected']} steps of the page's list. "
                          "Confirm the missing steps aren't needed to approve it.", 409)
    try:
        kb_store.save_entry(conn, entry, status="approved", actor=actor)
    except ValueError as exc:
        raise ReviewError(str(exc)) from None
    conn.execute("UPDATE kb_entries SET review_note = ? WHERE kb_entry_id = ?", (note.strip()[:500] or None, entry_id))
    audit.record(conn, actor, "kb.entry.approve", "kb_entry", entry_id,
                 flags=_flags(row, notes, len(entry["steps"])), **({"acknowledged_incomplete": gap} if gap else {}))
    _purge_if_decided(conn, row)


def reject(conn, entry_id: str, *, version: int, actor: str, note: str = "") -> None:
    row = _row(conn, entry_id)
    _check_version(row, version)
    conn.execute("UPDATE kb_entries SET status = 'rejected', reviewed_by = ?, reviewed_at = ?, review_note = ?, "
                 "updated_by = ?, updated_at = ?, version = version + 1 WHERE kb_entry_id = ?",
                 (actor, _now(), note.strip()[:500] or None, actor, _now(), entry_id))
    audit.record(conn, actor, "kb.entry.reject", "kb_entry", entry_id)
    _purge_if_decided(conn, row)


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------
def list_terms(conn, status: str | None = None) -> list[dict]:
    sql = ("SELECT t.term_id, t.label, t.kind, t.aliases, t.status, t.merged_into, t.evidence_quote, "
           "t.evidence_count, t.proposed_by, t.created_at, t.confirmed_by, t.confirmed_at, "
           "(SELECT COUNT(*) FROM kb_entry_terms et WHERE et.term_id = t.term_id) AS entry_count FROM kb_terms t")
    params = ()
    if status and status != "all":
        sql += " WHERE t.status = ?"
        params = (status,)
    sql += (" ORDER BY CASE t.status WHEN 'proposed' THEN 0 WHEN 'confirmed' THEN 1 ELSE 2 END, lower(t.label)")
    return [{**dict(r), "aliases": json.loads(r["aliases"])} for r in conn.execute(sql, params)]


def _term(conn, term_id: int) -> dict:
    row = conn.execute("SELECT * FROM kb_terms WHERE term_id = ?", (term_id,)).fetchone()
    if row is None:
        raise ReviewError("No such term", 404)
    return {**dict(row), "aliases": json.loads(row["aliases"])}


def propose_term(conn, term: dict, *, actor: str) -> int:
    label = str(term.get("label") or "").strip()
    if conn.execute("SELECT 1 FROM kb_terms WHERE lower(label) = lower(?)", (label,)).fetchone():
        raise ReviewError("A term with this label already exists", 409)
    proposal = {"label": label, "kind": term.get("kind"),
                "aliases": [a.strip() for a in term.get("aliases") or [] if isinstance(a, str) and a.strip()]}
    problems = kb_store.term_problems(proposal)
    if problems:
        raise ReviewError("; ".join(problems))
    term_id = kb_store.save_term(conn, proposal, status="proposed", actor=actor)
    audit.record(conn, actor, "kb.term.propose", "kb_term", str(term_id), kind=proposal["kind"])
    return term_id


def decide_term(conn, term_id: int, decision: str, *, actor: str) -> None:
    term = _term(conn, term_id)
    if term["status"] != "proposed":
        raise ReviewError("Only a proposed term can be decided", 409)
    if decision == "confirm":
        kb_store.save_term(conn, term, status="confirmed", actor=actor)
    elif decision == "reject":
        conn.execute("UPDATE kb_terms SET status = 'rejected', confirmed_by = ?, confirmed_at = ? WHERE term_id = ?",
                     (actor, _now(), term_id))
    else:
        raise ReviewError("Unknown decision")
    audit.record(conn, actor, f"kb.term.{decision}", "kb_term", str(term_id))


def merge_term(conn, term_id: int, into_term_id: int, *, actor: str) -> None:
    term, target = _term(conn, term_id), _term(conn, into_term_id)
    if term["status"] != "proposed":
        raise ReviewError("Only a proposed term can be merged", 409)
    if target["status"] != "confirmed" or term_id == into_term_id:
        raise ReviewError("A term can only be merged into another, confirmed term")
    aliases = [*target["aliases"], term["label"], *term["aliases"]]
    merged = {**target, "aliases": [a for a in dict.fromkeys(aliases) if a.lower() != target["label"].lower()]}
    try:
        kb_store.save_term(conn, merged, status="confirmed", actor=target["confirmed_by"] or actor)
    except ValueError as exc:
        raise ReviewError(str(exc)) from None
    for row in conn.execute("SELECT entry_id FROM kb_entry_terms WHERE term_id = ?", (term_id,)).fetchall():
        if not conn.execute("SELECT 1 FROM kb_entry_terms WHERE entry_id = ? AND term_id = ?",
                            (row["entry_id"], into_term_id)).fetchone():
            conn.execute("INSERT INTO kb_entry_terms (entry_id, term_id) VALUES (?, ?)", (row["entry_id"], into_term_id))
    conn.execute("DELETE FROM kb_entry_terms WHERE term_id = ?", (term_id,))
    conn.execute("UPDATE kb_terms SET status = 'merged', merged_into = ?, confirmed_by = ?, confirmed_at = ? "
                 "WHERE term_id = ?", (into_term_id, actor, _now(), term_id))
    audit.record(conn, actor, "kb.term.merge", "kb_term", str(term_id), into_term_id=into_term_id)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
def _move_drafts_asking_for(conn, name: str, to: str) -> int:
    moved = 0
    for row in conn.execute("SELECT kb_entry_id, draft_notes FROM kb_entries WHERE status = 'draft' "
                            "AND draft_notes LIKE ?", (f'%"proposed_category": "{name}"%',)).fetchall():
        if json.loads(row["draft_notes"] or "{}").get("proposed_category") == name:
            conn.execute("UPDATE kb_entries SET category = ?, version = version + 1 WHERE kb_entry_id = ?",
                         (to, row["kb_entry_id"]))
            moved += 1
    return moved


def decide_category(conn, name: str, decision: str, *, actor: str, into: str | None = None) -> int:
    """Returns how many drafts moved to the category."""
    status = {"confirm": "confirmed", "reject": "rejected", "merge": "merged"}.get(decision)
    if status is None:
        raise ReviewError("Unknown decision")
    try:
        categories.decide(conn, name, status, actor, merged_into=into)
    except LookupError:
        raise ReviewError("No such category", 404) from None
    except ValueError as exc:
        raise ReviewError(str(exc), 409) from None
    moved = 0
    if status in ("confirmed", "merged"):
        moved = _move_drafts_asking_for(conn, name, name if status == "confirmed" else into)
    audit.record(conn, actor, f"kb.category.{decision}", "kb_category", name,
                 **({"into": into} if into else {}), drafts_moved=moved)
    return moved
