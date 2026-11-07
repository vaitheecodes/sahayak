"""One chunk -> checked draft entries, proposed terms and categories.

  1. The chunk is checked for prompt-injection phrasing (flagged, never
     acted on), and its numbered procedures are read by code (steps.py).
  2. draft_kb_entries drafts entries (one model call). A procedure's entry
     rewrites its items one for one (count and order enforced by the
     operation); each step's quote is set here to the original item, and
     the entry records how many steps its list has (procedure_steps), so a
     reviewer sees "possibly incomplete (X of N)" when some are dropped.
  3. Code checks every other step's quote against the chunk; a step
     without a real passage is dropped (quote_missing / quote_length /
     quote_not_in_source).
  4. The answer must be a paraphrase (checks.answer_problem); one that
     isn't is removed (the entry stays if it still has steps).
  5. check_step_support asks a second time whether each remaining quote
     supports its step (one model call for the whole chunk); unsupported
     steps are dropped the same way (not_supported).
  6. A how-to left with no steps, or an entry with neither answer nor
     steps, is dropped. applies_to keeps only known or newly proposed
     terms; proposed terms need an evidence quote from the chunk.

No database access here: runs.py stores the result. Budget.spend() is
called before each model call; runs.py checks there is room for a whole
chunk (CALLS_PER_CHUNK) before starting one, so a run never stops halfway
through a chunk.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from backend import categories, kb_store
from backend.ai_service import draft_kb_entries as op
from backend.ai_service.schemas import DraftInput, StepToCheck
from kb_ingester import checks
from kb_ingester.steps import ordered_lists

# Drafting plus the step-support check: the most one chunk can cost.
CALLS_PER_CHUNK = 2


class CapReached(Exception):
    pass


class Budget:
    def __init__(self, cap: int):
        self.cap, self.used = cap, 0

    @property
    def left(self) -> int:
        return self.cap - self.used

    def spend(self) -> None:
        if self.used >= self.cap:
            raise CapReached()
        self.used += 1


@dataclass
class ChunkResult:
    entries: list[dict] = field(default_factory=list)  # pack format + "steps"[i] quote_offset/support_check
    terms: list[dict] = field(default_factory=list)  # {label, kind, aliases, evidence_quote}
    categories: list[dict] = field(default_factory=list)  # {name, label, description}
    signals: list[str] = field(default_factory=list)  # injection signals in the chunk
    dropped: Counter = field(default_factory=Counter)  # reason code -> count
    calls: int = 0


def _clean_aliases(label: str, aliases: list[str]) -> list[str]:
    seen, out = {label.lower()}, []
    for alias in aliases:
        alias = alias.strip()
        if alias and alias.lower() not in seen and kb_store.LABEL_PATTERN.match(alias):
            seen.add(alias.lower())
            out.append(alias)
    return out


def _terms(result, chunk_text: str, known: dict[str, str], dropped: Counter) -> list[dict]:
    terms = []
    for term in result.proposed_terms:
        label = term.label.strip()
        if label.lower() in known or any(t["label"].lower() == label.lower() for t in terms):
            continue
        proposal = {"label": label, "kind": term.kind, "aliases": _clean_aliases(label, term.aliases),
                    "evidence_quote": term.evidence_quote.strip()}
        if checks.quote_problem(proposal["evidence_quote"], chunk_text) or kb_store.term_problems(proposal):
            dropped["term_unsupported"] += 1
            continue
        terms.append(proposal)
    return terms


def draft_chunk(chunk_text: str, *, heading_path: str, page_title: str, source_url: str | None,
                known_terms: list[dict], budget: Budget) -> ChunkResult:
    """known_terms: confirmed and proposed terms ({label, kind, aliases})."""
    out = ChunkResult(signals=checks.injection_signals(chunk_text))
    procedures = ordered_lists(chunk_text)[:op.MAX_PROCEDURES]
    budget.spend()
    out.calls += 1
    drafted = op.draft_kb_entries(DraftInput(chunk_text=chunk_text, heading_path=heading_path,
                                             page_title=page_title, known_terms=known_terms,
                                             procedures=procedures))

    known = {t["label"].lower(): t["label"] for t in known_terms}
    out.terms = _terms(drafted, chunk_text, known, out.dropped)
    labels = {**known, **{t["label"].lower(): t["label"] for t in out.terms}}
    proposed_categories = {c.name: c for c in drafted.proposed_categories
                           if not categories.problem(c.name) and c.name not in categories.names()}

    # Procedures' entries first, then the rest, up to MAX_ENTRIES.
    ordered = sorted(drafted.entries, key=lambda d: (d.procedure is None or not procedures))
    if len(ordered) > op.MAX_ENTRIES:
        out.dropped["entries_over_cap"] += len(ordered) - op.MAX_ENTRIES
    entries = []
    for draft in ordered[:op.MAX_ENTRIES]:
        steps = []
        # A section without procedures ignores a stray procedure number.
        procedure = draft.procedure if procedures else None
        if procedure is not None:
            # The operation checked one step per item, in order.
            items = procedures[procedure - 1]
            steps = [{"text": step.text.strip(), "quote": item, "quote_offset": checks.quote_offset(item, chunk_text)}
                     for step, item in zip(draft.steps, items)]
        for step in draft.steps if procedure is None else []:
            problem = checks.quote_problem(step.quote, chunk_text)
            if problem:
                out.dropped[problem] += 1
                continue
            steps.append({"text": step.text.strip(), "quote": step.quote.strip(),
                          "quote_offset": checks.quote_offset(step.quote, chunk_text)})
        answer, notes = draft.answer.strip(), []
        problem = checks.answer_problem(answer, chunk_text) if answer else None
        if problem:
            out.dropped[problem] += 1
            notes.append(problem)
            answer = ""
        entries.append({"draft": draft, "steps": steps, "answer": answer, "notes": notes,
                        "procedure_steps": len(procedures[procedure - 1]) if procedure else None})

    to_check = [StepToCheck(id=n, step=s["text"], quote=s["quote"])
                for n, s in enumerate((s for e in entries for s in e["steps"]), start=1)]
    if to_check:
        budget.spend()
        out.calls += 1
        verdicts = {v.id: v.supported for v in op.check_step_support(to_check, heading_path).verdicts}
        n = 0
        for e in entries:
            kept = []
            for step in e["steps"]:
                n += 1
                if verdicts.get(n):
                    kept.append({**step, "support_check": "supported"})
                else:
                    out.dropped["not_supported"] += 1
            e["steps"] = kept

    used_categories = set()
    for e in entries:
        draft = e["draft"]
        if draft.kind == "how-to" and not e["steps"]:
            out.dropped["howto_without_steps"] += 1
            continue
        if not e["answer"] and not e["steps"]:
            out.dropped["empty_entry"] += 1
            continue
        fields = [draft.title, e["answer"], *draft.questions, *(s["text"] for s in e["steps"])]
        signals = checks.output_signals(fields, chunk_text)
        new_category = draft.new_category if draft.new_category in proposed_categories else None
        if new_category:
            used_categories.add(new_category)
        out.entries.append({
            "title": draft.title.strip(), "category": draft.category, "kind": draft.kind,
            "handling": "answer", "collect": [], "answer": e["answer"],
            "questions": list(dict.fromkeys(q.strip() for q in draft.questions if q.strip())),
            "steps": e["steps"], "source_url": source_url,
            "applies_to": sorted({labels[t.strip().lower()] for t in draft.applies_to
                                  if t.strip().lower() in labels}),
            "notes": {"removed": e["notes"], "output_signals": signals,
                      **({"proposed_category": new_category} if new_category else {}),
                      **({"procedure_steps": e["procedure_steps"]} if e["procedure_steps"] else {})},
        })
    out.categories = [{"name": c.name, "label": c.label.strip(), "description": c.description.strip()}
                      for name, c in proposed_categories.items() if name in used_categories]
    return out
