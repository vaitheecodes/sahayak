"""/api/kb/*: sources, runs, the review queue, terms and categories.

Roles (the admin is not a KB reviewer and gets 403 on every one):

  technicians + managers   read everything; edit drafts; propose terms
  managers only            add sources, estimate and start runs, approve
                           and reject entries, confirm / reject / merge
                           terms and categories
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import auth, categories, db, kb_store
from kb_ingester import review, runs

router = APIRouter(prefix="/api/kb")

_staff = auth.require_role("technician", "manager")
_manager = auth.require_role("manager")


def _http(exc: Exception) -> HTTPException:
    return HTTPException(status_code=getattr(exc, "status", 400), detail=str(exc))


class _Conn:
    """A connection that commits on success and rolls back on error."""

    def __enter__(self):
        self.conn = db.get_connection()
        return self.conn

    def __exit__(self, kind, exc, tb):
        try:
            if kind is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()


# ---------------------------------------------------------------------------
# Sources and runs
# ---------------------------------------------------------------------------
class SourceIn(BaseModel):
    name: str = Field(max_length=120)
    url: str = Field(max_length=2048)
    public_confirmed: bool = False


class StartIn(BaseModel):
    expected_model_calls: int = Field(ge=0)


@router.get("/sources")
def list_sources(_: str = Depends(_staff)):
    with _Conn() as conn:
        return {"sources": runs.list_sources(conn), "caps": runs.caps(conn)}


@router.post("/sources", status_code=201)
def create_source(body: SourceIn, manager_id: str = Depends(_manager)):
    try:
        with _Conn() as conn:
            return {"source_id": runs.create_source(conn, name=body.name, url=body.url,
                                                    public_confirmed=body.public_confirmed, actor=manager_id)}
    except runs.RunError as exc:
        raise _http(exc) from None


@router.get("/sources/{source_id}/runs")
def source_runs(source_id: int, _: str = Depends(_staff)):
    with _Conn() as conn:
        return {"runs": runs.list_runs(conn, source_id)}


@router.post("/sources/{source_id}/estimate")
def estimate(source_id: int, manager_id: str = Depends(_manager)):
    try:
        return runs.estimate(source_id, manager_id)
    except runs.RunError as exc:
        raise _http(exc) from None


@router.post("/runs/{run_id}/start")
def start_run(run_id: int, body: StartIn, tasks: BackgroundTasks, manager_id: str = Depends(_manager)):
    try:
        run = runs.start(run_id, manager_id, body.expected_model_calls)
    except runs.RunError as exc:
        raise _http(exc) from None
    tasks.add_task(runs.execute, run_id)
    return run


@router.get("/runs/{run_id}")
def get_run(run_id: int, _: str = Depends(_staff)):
    with _Conn() as conn:
        run = runs.get_run(conn, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such run")
    return run


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------
class StepIn(BaseModel):
    text: str = Field(max_length=400)
    quote: str = Field(max_length=400)


class EntryEdit(BaseModel):
    version: int
    title: str | None = Field(default=None, max_length=120)
    category: str | None = None
    kind: Literal["how-to", "troubleshooting"] | None = None
    questions: list[str] | None = Field(default=None, max_length=kb_store.MAX_QUESTIONS)
    answer: str | None = Field(default=None, max_length=1500)
    steps: list[StepIn] | None = Field(default=None, max_length=kb_store.MAX_STEPS)
    applies_to: list[str] | None = Field(default=None, max_length=10)


class Decision(BaseModel):
    version: int
    note: str = Field(default="", max_length=500)


@router.get("/entries")
def list_entries(status: Literal["draft", "approved", "rejected", "retired", "all"] = "draft",
                 flag: Literal["duplicate", "stale", "injection", "answer_removed"] | None = None,
                 source_id: int | None = None, _: str = Depends(_staff)):
    with _Conn() as conn:
        return {"entries": review.list_entries(conn, status=status, flag=flag, source_id=source_id)}


@router.get("/entries/{entry_id}")
def entry_detail(entry_id: str, _: str = Depends(_staff)):
    try:
        with _Conn() as conn:
            return review.entry_detail(conn, entry_id)
    except review.ReviewError as exc:
        raise _http(exc) from None


@router.patch("/entries/{entry_id}")
def edit_entry(entry_id: str, body: EntryEdit, staff_id: str = Depends(_staff)):
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    if "steps" in changes:
        changes["steps"] = [s.model_dump() for s in body.steps or []]
    try:
        with _Conn() as conn:
            changed = review.update_draft(conn, entry_id, changes, version=body.version, actor=staff_id)
            detail = review.entry_detail(conn, entry_id)
        return {**detail, "changed": changed}
    except review.ReviewError as exc:
        raise _http(exc) from None


def _decide(entry_id: str, body: Decision, manager_id: str, action) -> dict:
    try:
        with _Conn() as conn:
            action(conn, entry_id, version=body.version, actor=manager_id, note=body.note)
    except review.ReviewError as exc:
        raise _http(exc) from None
    kb_store.changed()
    with _Conn() as conn:
        return review.entry_detail(conn, entry_id)


@router.post("/entries/{entry_id}/approve")
def approve_entry(entry_id: str, body: Decision, manager_id: str = Depends(_manager)):
    return _decide(entry_id, body, manager_id, review.approve)


@router.post("/entries/{entry_id}/reject")
def reject_entry(entry_id: str, body: Decision, manager_id: str = Depends(_manager)):
    return _decide(entry_id, body, manager_id, review.reject)


# ---------------------------------------------------------------------------
# Terms and categories
# ---------------------------------------------------------------------------
class TermIn(BaseModel):
    label: str = Field(max_length=41)
    kind: Literal[kb_store.TERM_KINDS]  # type: ignore[valid-type]
    aliases: list[str] = Field(default_factory=list, max_length=10)


class MergeIn(BaseModel):
    into: int


class CategoryMergeIn(BaseModel):
    into: str


@router.get("/terms")
def list_terms(status: Literal["proposed", "confirmed", "rejected", "merged", "all"] = "all",
               _: str = Depends(_staff)):
    with _Conn() as conn:
        return {"terms": review.list_terms(conn, status)}


@router.post("/terms", status_code=201)
def propose_term(body: TermIn, staff_id: str = Depends(_staff)):
    try:
        with _Conn() as conn:
            return {"term_id": review.propose_term(conn, body.model_dump(), actor=staff_id)}
    except review.ReviewError as exc:
        raise _http(exc) from None


def _term_action(fn) -> dict:
    try:
        with _Conn() as conn:
            fn(conn)
    except review.ReviewError as exc:
        raise _http(exc) from None
    kb_store.changed()
    return {"ok": True}


@router.post("/terms/{term_id}/confirm")
def confirm_term(term_id: int, manager_id: str = Depends(_manager)):
    return _term_action(lambda conn: review.decide_term(conn, term_id, "confirm", actor=manager_id))


@router.post("/terms/{term_id}/reject")
def reject_term(term_id: int, manager_id: str = Depends(_manager)):
    return _term_action(lambda conn: review.decide_term(conn, term_id, "reject", actor=manager_id))


@router.post("/terms/{term_id}/merge")
def merge_term(term_id: int, body: MergeIn, manager_id: str = Depends(_manager)):
    return _term_action(lambda conn: review.merge_term(conn, term_id, body.into, actor=manager_id))


@router.get("/categories")
def list_categories(_: str = Depends(_staff)):
    with _Conn() as conn:
        return {"categories": categories.all_rows(conn)}


def _category_action(name: str, decision: str, manager_id: str, into: str | None = None) -> dict:
    try:
        with _Conn() as conn:
            moved = review.decide_category(conn, name, decision, actor=manager_id, into=into)
    except review.ReviewError as exc:
        # categories.decide reloaded the cache from the rolled-back connection.
        with _Conn() as conn:
            categories.load(conn)
        raise _http(exc) from None
    with _Conn() as conn:
        categories.load(conn)
    return {"drafts_moved": moved}


@router.post("/categories/{name}/confirm")
def confirm_category(name: str, manager_id: str = Depends(_manager)):
    return _category_action(name, "confirm", manager_id)


@router.post("/categories/{name}/reject")
def reject_category(name: str, manager_id: str = Depends(_manager)):
    return _category_action(name, "reject", manager_id)


@router.post("/categories/{name}/merge")
def merge_category(name: str, body: CategoryMergeIn, manager_id: str = Depends(_manager)):
    return _category_action(name, "merge", manager_id, body.into)
