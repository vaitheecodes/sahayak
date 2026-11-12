"""Sources, runs and what a run stores.

A source is added with a confirmation that its content is public or
allowed to be used; who confirmed it and when are stored with it.

A run has two steps, so nobody starts paying for model calls blind:

  estimate(source)  fetches and chunks the page (no model calls) and
                    records what drafting it would cost: chunks to draft
                    x CALLS_PER_CHUNK model calls (status "estimated").
                    An unchanged page (same content hash) or a page whose
                    chunks were all drafted before costs nothing and
                    finishes at once.
  start(run)        the caller repeats the estimate it showed; the run is
                    given a model-call cap of at most the per-run cap and
                    what is left of today's cap (KB settings), reserved
                    under a lock so two runs can't both spend it.
  execute(run)      (a background task) drafts chunk by chunk; before
                    each chunk it needs room for a whole chunk, so at the
                    cap it stops cleanly between chunks (status
                    "stopped", stop_reason run_cap / daily_cap). The
                    next run resumes: drafted chunks are skipped by hash.

A document's content_hash moves to the new version only once every chunk
of it is drafted; entries drafted from chunks that are no longer in the
page are then flagged stale. Errors are counted by reason code only.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from collections import Counter
from datetime import timedelta

from backend import app_settings, audit, categories, db, kb_store
from backend.ai_service import AIError
from backend.timeutil import utcnow
from kb_ingester import chunking, clean, dedupe
from kb_ingester.drafting import CALLS_PER_CHUNK, Budget, CapReached, draft_chunk
from kb_ingester.safe_fetch import FetchError, SafeFetcher, address_problem, check_url
from kb_ingester.files import DocumentProblem
from kb_ingester.sources import RawDocument, UrlSource

logger = logging.getLogger(__name__)

SOURCE_KINDS = ("url", "file", "text")
ACTIVE = ("queued", "running")
FINISHED = ("done", "stopped", "failed", "cancelled")
STEP_DROPS = ("quote_missing", "quote_length", "quote_not_in_source", "not_supported")
MAX_CONSECUTIVE_AI_FAILURES = 3
SYSTEM = "system:kb_ingester"

# Tests replace this to serve pages without a network.
fetcher_factory = SafeFetcher


class RunError(Exception):
    """A request the run rules refuse; `status` is the HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return utcnow().isoformat()


def settings():
    return app_settings.get("kb")


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
def _is_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def create_source(conn, *, name: str, url: str | None = None, public_confirmed: bool, actor: str,
                  licence_note: str = "", kind: str = "url") -> int:
    """kind: url (a web page at `url`), file (an uploaded TXT/MD/PDF) or
    text (pasted text); file and text sources get their content with each
    estimate (files.py). licence_note: the content's licence / attribution,
    if it has one (e.g. "CC BY-SA 4.0, Odoo S.A."); copied onto every entry
    drafted from the source, next to the source URL."""
    if kind not in SOURCE_KINDS:
        raise RunError("Unknown source kind")
    if public_confirmed is not True:
        raise RunError("Confirm that this content is public or that you are allowed to use it")
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise RunError("Name the source (at most 120 characters)")
    if kind == "url":
        try:
            target = check_url(url)
            literal = target.host.strip("[]")
            if _is_address(literal) and address_problem(literal):
                raise FetchError(address_problem(literal))
        except FetchError as exc:
            raise RunError(f"This URL can't be used ({exc.code})") from None
        url = url.strip()
    else:
        url = None
    licence_note = (licence_note or "").strip()
    if len(licence_note) > 200:
        raise RunError("The licence note can be at most 200 characters")
    if url and conn.execute("SELECT 1 FROM kb_sources WHERE root_url = ? AND active = 1", (url,)).fetchone():
        raise RunError("This URL is already a source", 409)
    now = _now()
    source_id = conn.execute(
        "INSERT INTO kb_sources (kind, name, root_url, config, public_confirmed_by, public_confirmed_at, "
        "created_by, created_at, licence_note) VALUES (?, ?, ?, '{}', ?, ?, ?, ?, ?) RETURNING source_id",
        (kind, name, url, actor, now, actor, now, licence_note or None)).fetchone()["source_id"]
    audit.record(conn, actor, "kb.source.create", "kb_source", str(source_id), kind=kind)
    return source_id


def _run_row(row) -> dict:
    run = dict(row)
    run["errors"] = json.loads(run.get("errors") or "{}")
    estimate = json.loads(run.get("estimate") or "{}")
    estimate.pop("chunk_hashes", None)
    run["estimate"] = estimate
    return run


def get_run(conn, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM kb_ingest_runs WHERE run_id = ?", (run_id,)).fetchone()
    return _run_row(row) if row else None


def staff_name(conn, actor: str | None) -> str | None:
    """A staff member's name for an actor id (system actors as they are)."""
    if not actor:
        return None
    row = conn.execute("SELECT name FROM staff WHERE staff_id = ?", (actor,)).fetchone()
    return row["name"] if row else actor


def list_sources(conn) -> list[dict]:
    sources = [dict(r) for r in conn.execute("SELECT * FROM kb_sources WHERE active = 1 ORDER BY source_id")]
    for source in sources:
        source["public_confirmed_by_name"] = staff_name(conn, source["public_confirmed_by"])
        source["config"] = json.loads(source.get("config") or "{}")
        last = conn.execute("SELECT * FROM kb_ingest_runs WHERE source_id = ? ORDER BY run_id DESC LIMIT 1",
                            (source["source_id"],)).fetchone()
        source["last_run"] = _run_row(last) if last else None
        source["entries"] = {r["status"]: r["n"] for r in conn.execute(
            "SELECT e.status, COUNT(*) AS n FROM kb_entries e JOIN kb_documents d ON d.document_id = e.document_id "
            "WHERE d.source_id = ? GROUP BY e.status", (source["source_id"],))}
    return sources


def list_runs(conn, source_id: int, limit: int = 20) -> list[dict]:
    return [_run_row(r) for r in conn.execute(
        "SELECT * FROM kb_ingest_runs WHERE source_id = ? ORDER BY run_id DESC LIMIT ?", (source_id, limit))]


# ---------------------------------------------------------------------------
# Caps
# ---------------------------------------------------------------------------
def calls_used_today(conn) -> int:
    """Model calls spent or reserved since 00:00 UTC: finished runs count
    what they used, queued and running ones their whole cap."""
    since = utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    used = 0
    for row in conn.execute(
            # A run still active counts whatever day it started: one started
            # before 00:00 UTC must not free its reservation at midnight.
            f"SELECT status, model_calls, model_call_cap FROM kb_ingest_runs WHERE (created_at >= ? "
            f"OR status IN {ACTIVE}) AND status IN ('queued', 'running', 'done', 'stopped', 'failed')", (since,)):
        used += row["model_call_cap"] if row["status"] in ACTIVE else row["model_calls"]
    return used


def caps(conn) -> dict:
    kb = settings()
    used = calls_used_today(conn)
    return {"per_run": kb.model_calls_per_run, "per_day": kb.model_calls_per_day, "used_today": used,
            "left_today": max(0, kb.model_calls_per_day - used), "calls_per_chunk": CALLS_PER_CHUNK}


# ---------------------------------------------------------------------------
# Estimate
# ---------------------------------------------------------------------------
def _check_can_run(conn, source_id: int, actor: str) -> dict:
    source = conn.execute("SELECT * FROM kb_sources WHERE source_id = ? AND active = 1", (source_id,)).fetchone()
    if source is None:
        raise RunError("No such source", 404)
    if conn.execute(f"SELECT 1 FROM kb_ingest_runs WHERE source_id = ? AND status IN {ACTIVE}",
                    (source_id,)).fetchone():
        raise RunError("This source already has a run in progress", 409)
    hour_ago = (utcnow() - timedelta(hours=1)).isoformat()
    recent = conn.execute("SELECT COUNT(*) FROM kb_ingest_runs WHERE triggered_by = ? AND created_at >= ?",
                          (actor, hour_ago)).fetchone()[0]
    if recent >= settings().runs_per_hour:
        raise RunError("Too many runs in the last hour; try again later", 429)
    return dict(source)


def _new_run(conn, source_id: int, actor: str) -> int:
    return conn.execute(
        "INSERT INTO kb_ingest_runs (source_id, status, triggered_by, created_at, model_call_cap) "
        "VALUES (?, 'estimated', ?, ?, 0) RETURNING run_id", (source_id, actor, _now())).fetchone()["run_id"]


def _document(conn, source_id: int, doc: RawDocument) -> dict:
    row = conn.execute("SELECT * FROM kb_documents WHERE source_id = ? AND location = ?",
                       (source_id, doc.location)).fetchone()
    if row:
        return dict(row)
    return dict(conn.execute(
        "INSERT INTO kb_documents (source_id, location, state) VALUES (?, ?, 'new') RETURNING *",
        (source_id, doc.location)).fetchone())


def estimate(source_id: int, actor: str, upload: RawDocument | None = None, filename: str | None = None) -> dict:
    """Fetch (a web page) or take (`upload`: a file or pasted text) the
    source's content and chunk it, with no model calls; returns the run."""
    conn = db.get_connection()
    try:
        source = _check_can_run(conn, source_id, actor)
        if source["kind"] == "url" and upload is not None:
            raise RunError("A web page source is read from its URL")
        if source["kind"] != "url" and upload is None:
            raise RunError("Upload the file or paste the text again to run this source: its content isn't kept")
        if filename:
            config = {**json.loads(source.get("config") or "{}"), "filename": filename}
            conn.execute("UPDATE kb_sources SET config = ? WHERE source_id = ?", (json.dumps(config), source_id))
        conn.execute("UPDATE kb_ingest_runs SET status = 'cancelled', finished_at = ?, stop_reason = 'replaced' "
                     "WHERE source_id = ? AND status = 'estimated'", (_now(), source_id))
        conn.commit()
    finally:
        conn.close()

    # The network part holds no database connection.
    documents = [upload] if upload is not None else list(UrlSource(source["root_url"], fetcher_factory()).documents())

    conn = db.get_connection()
    try:
        db.begin_write(conn, f"kb-source-{source_id}")
        run_id = _new_run(conn, source_id, actor)
        totals = Counter()
        errors = Counter()
        hashes: list[str] = []
        for doc in documents:
            if not isinstance(doc, RawDocument):
                errors[doc.code] += 1
                totals["pages_skipped"] += 1
                conn.execute("INSERT INTO kb_documents (source_id, location, state, http_status, miss_count) "
                             "VALUES (?, ?, 'error', ?, 1) ON CONFLICT (source_id, location) DO UPDATE SET "
                             "state = 'error', http_status = excluded.http_status, "
                             "miss_count = kb_documents.miss_count + 1",
                             (source_id, doc.location, doc.status))
                continue
            try:
                cleaned = clean.to_text(doc.body, doc.content_type, doc.charset)
            except DocumentProblem as exc:
                # e.g. a scanned PDF: no text to draft from (no OCR).
                errors[exc.code] += 1
                totals["pages_skipped"] += 1
                continue
            totals["pages"] += 1
            new_hash = chunking.content_hash(cleaned.text)
            document = _document(conn, source_id, doc)
            conn.execute("UPDATE kb_documents SET url = ?, title = ?, http_status = 200, etag = ?, last_modified = ?, "
                         "byte_size = ?, fetched_at = ?, miss_count = 0 WHERE document_id = ?",
                         (doc.url, cleaned.title, doc.etag, doc.last_modified, len(doc.body), doc.fetched_at,
                          document["document_id"]))
            if document.get("content_hash") == new_hash:
                totals["pages_unchanged"] += 1
                conn.execute("UPDATE kb_documents SET state = 'current', pending_hash = NULL WHERE document_id = ?",
                             (document["document_id"],))
                continue
            chunks, capped = chunking.chunk_text(cleaned.text)
            if capped:
                errors["chunks_capped"] += capped
            drafted = {r["chunk_hash"] for r in conn.execute(
                "SELECT chunk_hash FROM kb_chunks WHERE document_id = ? AND drafted_at IS NOT NULL",
                (document["document_id"],))}
            # Chunks an earlier estimate prepared but never drafted.
            conn.execute("DELETE FROM kb_chunks WHERE document_id = ? AND drafted_at IS NULL",
                         (document["document_id"],))
            todo = [c for c in chunks if c.hash not in drafted]
            hashes += [c.hash for c in chunks]
            conn.executemany(
                "INSERT INTO kb_chunks (document_id, run_id, ordinal, heading_path, text, chunk_hash, char_start, "
                "char_end) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(document["document_id"], run_id, c.ordinal, c.heading_path, c.text, c.hash, c.start, c.end)
                 for c in todo])
            conn.execute("UPDATE kb_documents SET pending_hash = ?, state = ? WHERE document_id = ?",
                         (new_hash, "changed" if document.get("content_hash") else "new", document["document_id"]))
            totals["chunks"] += len(chunks)
            totals["chunks_unchanged"] += len(chunks) - len(todo)
            totals["chunks_to_draft"] += len(todo)
            if not todo:
                _finish_document(conn, document["document_id"], set(c.hash for c in chunks))

        limits = caps(conn)
        calls = totals["chunks_to_draft"] * CALLS_PER_CHUNK
        estimate_info = {
            "pages": totals["pages"], "pages_unchanged": totals["pages_unchanged"],
            "pages_skipped": totals["pages_skipped"], "chunks": totals["chunks"],
            "chunks_unchanged": totals["chunks_unchanged"], "chunks_to_draft": totals["chunks_to_draft"],
            "calls_per_chunk": CALLS_PER_CHUNK, "model_calls": calls, "caps": limits,
            "chunk_hashes": hashes,
        }
        status, stop = "estimated", None
        if not calls:
            status = "failed" if totals["pages_skipped"] and not totals["pages"] else "done"
            stop = next(iter(errors), "fetch_failed") if status == "failed" else "nothing_to_draft"
        conn.execute(
            "UPDATE kb_ingest_runs SET status = ?, stop_reason = ?, estimated_model_calls = ?, estimate = ?, "
            "pages_fetched = ?, pages_unchanged = ?, pages_skipped = ?, errors = ?, finished_at = ? WHERE run_id = ?",
            (status, stop, calls, json.dumps(estimate_info), totals["pages"], totals["pages_unchanged"],
             totals["pages_skipped"], json.dumps(dict(errors)), None if status == "estimated" else _now(), run_id))
        audit.record(conn, actor, "kb.run.estimate", "kb_run", str(run_id), source_id=source_id,
                     model_calls=calls, status=status)
        conn.commit()
        return get_run(conn, run_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Start and execute
# ---------------------------------------------------------------------------
def start(run_id: int, actor: str, expected_model_calls: int) -> dict:
    conn = db.get_connection()
    try:
        db.begin_write(conn, "kb-model-calls")
        run = get_run(conn, run_id)
        if run is None:
            raise RunError("No such run", 404)
        if run["status"] != "estimated":
            raise RunError("Only an estimated run can be started", 409)
        if expected_model_calls != run["estimated_model_calls"]:
            raise RunError("The estimate has changed; estimate again", 409)
        if conn.execute(f"SELECT 1 FROM kb_ingest_runs WHERE source_id = ? AND status IN {ACTIVE}",
                        (run["source_id"],)).fetchone():
            raise RunError("This source already has a run in progress", 409)
        limits = caps(conn)
        cap = min(limits["per_run"], limits["left_today"], run["estimated_model_calls"])
        if cap < CALLS_PER_CHUNK:
            raise RunError("Today's model-call cap is used up; try again tomorrow", 429)
        cap_reason = "daily_cap" if limits["left_today"] < limits["per_run"] else "run_cap"
        estimate_info = json.loads(conn.execute("SELECT estimate FROM kb_ingest_runs WHERE run_id = ?",
                                                (run_id,)).fetchone()["estimate"])
        estimate_info["cap_reason"] = cap_reason
        conn.execute("UPDATE kb_ingest_runs SET status = 'queued', model_call_cap = ?, triggered_by = ?, "
                     "estimate = ? WHERE run_id = ?", (cap, actor, json.dumps(estimate_info), run_id))
        audit.record(conn, actor, "kb.run.start", "kb_run", str(run_id), model_call_cap=cap,
                     estimated_model_calls=run["estimated_model_calls"])
        conn.commit()
        return get_run(conn, run_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _known_terms(conn) -> list[dict]:
    return [{"label": r["label"], "kind": r["kind"], "aliases": json.loads(r["aliases"])} for r in conn.execute(
        "SELECT label, kind, aliases FROM kb_terms WHERE status IN ('confirmed', 'proposed') ORDER BY label")]


def _save_terms(conn, terms: list[dict], chunk_id: int) -> None:
    for term in terms:
        row = conn.execute("SELECT term_id, status FROM kb_terms WHERE lower(label) = lower(?)",
                           (term["label"],)).fetchone()
        if row is None:
            term_id = kb_store.save_term(conn, term, status="proposed", actor=SYSTEM)
            conn.execute("UPDATE kb_terms SET evidence_chunk_id = ?, evidence_count = 1 WHERE term_id = ?",
                         (chunk_id, term_id))
        elif row["status"] == "proposed":
            conn.execute("UPDATE kb_terms SET evidence_count = evidence_count + 1 WHERE term_id = ?",
                         (row["term_id"],))


def save_chunk_result(conn, run: dict, chunk: dict, result) -> int:
    """Store one chunk's drafts, terms and categories, and mark it
    drafted. Returns the number of entries saved. The caller commits."""
    _save_terms(conn, result.terms, chunk["chunk_id"])
    for category in result.categories:
        categories.add(conn, category["name"], category["label"], category["description"],
                       status="proposed", source="ingester")
    usable_terms = set(kb_store._term_ids(conn, include_proposed=True))
    existing = kb_store._entries(conn, "WHERE status IN ('draft', 'approved')")
    saved = 0
    for entry in result.entries:
        entry = {**entry, "applies_to": [t for t in entry["applies_to"] if t in usable_terms]}
        if chunk.get("licence_note"):
            entry["source_licence"] = chunk["licence_note"]
        notes = {k: v for k, v in entry.pop("notes").items() if v}
        if result.signals:
            notes["chunk_signals"] = result.signals
        match = dedupe.best_match(entry, existing)
        draft = {"document_id": chunk["document_id"], "chunk_id": chunk["chunk_id"],
                 "chunk_hash": chunk["chunk_hash"], "run_id": run["run_id"], "draft_notes": notes,
                 "duplicate_of": match[0] if match else None, "duplicate_score": match[1] if match else None}
        try:
            entry_id = kb_store.save_entry(conn, entry, status="draft", actor=SYSTEM, draft=draft)
        except ValueError:
            result.dropped["invalid_entry"] += 1
            continue
        existing.append({**entry, "kb_entry_id": entry_id})
        saved += 1
    conn.execute("UPDATE kb_chunks SET drafted_at = ?, flagged_injection = ? WHERE chunk_id = ?",
                 (_now(), 1 if result.signals else 0, chunk["chunk_id"]))
    return saved


def _finish_document(conn, document_id: int, hashes: set[str]) -> None:
    """Every chunk drafted: the new version is the current one, and
    entries from chunks no longer in it are stale."""
    conn.execute("UPDATE kb_documents SET content_hash = pending_hash, pending_hash = NULL, state = 'current' "
                 "WHERE document_id = ? AND pending_hash IS NOT NULL", (document_id,))
    rows = conn.execute("SELECT kb_entry_id, chunk_hash, status FROM kb_entries WHERE document_id = ? "
                        "AND stale = 0 AND status IN ('draft', 'approved')", (document_id,)).fetchall()
    stale = [r["kb_entry_id"] for r in rows if r["chunk_hash"] not in hashes]
    for entry_id in stale:
        conn.execute("UPDATE kb_entries SET stale = 1 WHERE kb_entry_id = ?", (entry_id,))


def _add_counts(conn, run_id: int, **counts) -> None:
    sets = ", ".join(f"{k} = {k} + ?" for k in counts)
    conn.execute(f"UPDATE kb_ingest_runs SET {sets} WHERE run_id = ?", (*counts.values(), run_id))


def _add_errors(conn, run_id: int, extra: Counter) -> None:
    if not extra:
        return
    row = conn.execute("SELECT errors FROM kb_ingest_runs WHERE run_id = ?", (run_id,)).fetchone()
    errors = Counter(json.loads(row["errors"] or "{}"))
    errors.update(extra)
    conn.execute("UPDATE kb_ingest_runs SET errors = ? WHERE run_id = ?", (json.dumps(dict(errors)), run_id))


def execute(run_id: int) -> None:
    """Draft a queued run's chunks (a background task). Never raises."""
    try:
        _execute(run_id)
    except Exception as exc:  # noqa: BLE001 — a background task must leave the run in a final state
        logger.error("KB run %s failed: %s", run_id, type(exc).__name__)
        conn = db.get_connection()
        try:
            conn.execute("UPDATE kb_ingest_runs SET status = 'failed', stop_reason = 'internal_error', "
                         "finished_at = ? WHERE run_id = ? AND status IN ('queued', 'running')", (_now(), run_id))
            conn.commit()
        finally:
            conn.close()


def _execute(run_id: int) -> None:
    conn = db.get_connection()
    try:
        run = get_run(conn, run_id)
        if run is None or run["status"] != "queued":
            return
        conn.execute("UPDATE kb_ingest_runs SET status = 'running', started_at = ? WHERE run_id = ?", (_now(), run_id))
        conn.commit()
        estimate_info = json.loads(conn.execute("SELECT estimate FROM kb_ingest_runs WHERE run_id = ?",
                                                (run_id,)).fetchone()["estimate"])
        chunks = [dict(r) for r in conn.execute(
            "SELECT c.*, d.url, d.title AS page_title, s.licence_note FROM kb_chunks c "
            "JOIN kb_documents d ON d.document_id = c.document_id JOIN kb_sources s ON s.source_id = d.source_id "
            "WHERE c.run_id = ? AND c.drafted_at IS NULL AND c.text IS NOT NULL ORDER BY c.document_id, c.ordinal",
            (run_id,))]
    finally:
        conn.close()

    budget = Budget(run["model_call_cap"])
    stop, failures = None, 0
    for chunk in chunks:
        if budget.left < CALLS_PER_CHUNK:
            stop = estimate_info.get("cap_reason", "run_cap")
            break
        conn = db.get_connection()
        try:
            terms = _known_terms(conn)
        finally:
            conn.close()
        before = budget.used
        try:
            # No connection is held during the model calls.
            result = draft_chunk(chunk["text"], heading_path=chunk["heading_path"], page_title=chunk["page_title"] or "",
                                 source_url=chunk["url"], known_terms=terms, budget=budget)
        except CapReached:
            # Retries used up the cap mid-chunk: it stays undrafted for the next run.
            conn = db.get_connection()
            try:
                _add_counts(conn, run_id, model_calls=budget.used - before)
                conn.commit()
            finally:
                conn.close()
            stop = estimate_info.get("cap_reason", "run_cap")
            break
        except AIError:
            failures += 1
            conn = db.get_connection()
            try:
                _add_counts(conn, run_id, model_calls=budget.used - before)
                _add_errors(conn, run_id, Counter(ai_unavailable=1))
                conn.commit()
            finally:
                conn.close()
            if failures >= MAX_CONSECUTIVE_AI_FAILURES:
                stop = "ai_unavailable"
                break
            continue
        failures = 0
        conn = db.get_connection()
        try:
            db.begin_write(conn, "kb-entries")
            saved = save_chunk_result(conn, run, chunk, result)
            _add_counts(conn, run_id, model_calls=result.calls, chunks=1, drafts_created=saved,
                        steps_rejected=sum(result.dropped[c] for c in STEP_DROPS))
            _add_errors(conn, run_id, result.dropped)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    conn = db.get_connection()
    try:
        db.begin_write(conn, "kb-entries")
        documents = {c["document_id"] for c in chunks}
        for document_id in documents:
            left = conn.execute("SELECT COUNT(*) FROM kb_chunks WHERE document_id = ? AND drafted_at IS NULL",
                                (document_id,)).fetchone()[0]
            if not left:
                _finish_document(conn, document_id, set(estimate_info.get("chunk_hashes") or []))
        status = "done" if stop is None else ("failed" if stop == "ai_unavailable" else "stopped")
        conn.execute("UPDATE kb_ingest_runs SET status = ?, stop_reason = ?, finished_at = ? WHERE run_id = ?",
                     (status, stop, _now(), run_id))
        purge_chunks(conn)
        final = get_run(conn, run_id)
        audit.record(conn, SYSTEM, "kb.run.finish", "kb_run", str(run_id), status=status, stop_reason=stop,
                     model_calls=final["model_calls"], drafts_created=final["drafts_created"])
        conn.commit()
    finally:
        conn.close()
    kb_store.changed()


def recover_interrupted() -> None:
    """At startup: runs left queued or running by a restart are failed."""
    conn = db.get_connection()
    try:
        conn.execute("UPDATE kb_ingest_runs SET status = 'failed', stop_reason = 'interrupted', finished_at = ? "
                     "WHERE status IN ('queued', 'running')", (_now(),))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Chunk retention
# ---------------------------------------------------------------------------
def purge_chunks(conn) -> int:
    """Drop the text of drafted chunks with no draft left to decide, and
    of any chunk older than the retention period. The caller commits."""
    cutoff = (utcnow() - timedelta(days=settings().chunk_retention_days)).isoformat()
    ids = [r["chunk_id"] for r in conn.execute(
        "SELECT chunk_id FROM kb_chunks c WHERE c.text IS NOT NULL AND ("
        "  (c.drafted_at IS NOT NULL AND NOT EXISTS (SELECT 1 FROM kb_entries e WHERE e.chunk_id = c.chunk_id "
        "   AND e.status = 'draft')) "
        "  OR c.drafted_at < ? "
        "  OR (c.drafted_at IS NULL AND c.run_id IN (SELECT run_id FROM kb_ingest_runs WHERE created_at < ?)))",
        (cutoff, cutoff))]
    now = _now()
    for chunk_id in ids:
        conn.execute("UPDATE kb_chunks SET text = NULL, purged_at = ? WHERE chunk_id = ?", (now, chunk_id))
    return len(ids)
