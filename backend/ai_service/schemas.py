"""Input and output schemas for every AI operation.

Outputs are what the model must produce; provider.complete_json validates
them (one retry) before anything is saved. Lengths are capped so a
runaway response can't bloat the database or the UI. Fields the model
must not control (`source`) are hidden from the schema it sees and set by
code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, create_model
from pydantic.json_schema import SkipJsonSchema

# A category name. Which names exist is data (backend/categories.py):
# operations that return one narrow it to the current names with
# with_categories(), so the schema the model sees lists them.
Category = Annotated[str, Field(min_length=1, max_length=41)]


def with_categories(schema: type[BaseModel], names: list[str], *, optional: bool = False) -> type[BaseModel]:
    """`schema` with its `category` field limited to `names`."""
    allowed = Literal[tuple(names)]  # type: ignore[valid-type]
    field = (allowed | None, None) if optional else (allowed, ...)
    return create_model(schema.__name__, __base__=schema, category=field)


def _text(max_length: int = 2000):
    return Field(min_length=1, max_length=max_length)


def _items(max_length: int = 12, **kwargs):
    return Field(default_factory=list, max_length=max_length, **kwargs)


Source = SkipJsonSchema[Literal["ai", "fallback"]]


# ---------------------------------------------------------------------------
# Shared inputs
# ---------------------------------------------------------------------------
class KBCandidate(BaseModel):
    kb_entry_id: str
    category: str
    intent: str
    instruction: str
    response: str
    score: float
    handling: str = "answer"
    collect: list[str] = []
    kind: str | None = None


class HistoryItem(BaseModel):
    ticket_text: str
    category: str | None = None
    status: str | None = None


# ---------------------------------------------------------------------------
# categorize_ticket
# ---------------------------------------------------------------------------
class CategorizeInput(BaseModel):
    ticket_text: str
    history: list[HistoryItem] = []
    kb_candidates: list[KBCandidate] = []


class Categorization(BaseModel):
    category: Category
    confidence: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# chat_response
# ---------------------------------------------------------------------------
class AnswerInput(BaseModel):
    ticket_text: str
    category: str | None = None
    history: list[HistoryItem] = []
    kb_candidates: list[KBCandidate] = []
    continuation: bool = False
    reply_format: Literal["chat", "email"] = "chat"
    customer_name: str | None = None
    # Set by graph._reply_context: KB topics that matched words but are
    # specific to something the customer hasn't mentioned (never grounding),
    # what the customer has told us (product area, picked category), and
    # whether the product area is known (chat filter's fallback question).
    unconfirmed_topics: list[str] = []
    customer_details: str = ""
    subject_known: bool = True
    subject: str | None = None
    # No symptom described yet ("I have an issue"): one open question,
    # no grounding (chat_response.open_question).
    vague: bool = False
    # The AI's last replies in this conversation (repeat guard) and the
    # customer's latest message (answered first when it asks a question).
    recent_ai_replies: list[str] = []
    latest_message: str = ""
    # A how-to request (backend/request_kind.py): no troubleshooting
    # boilerplate. error_reported: the customer mentioned an error, so a
    # reply may ask for the exact error text (never otherwise).
    how_to: bool = False
    error_reported: bool = True


class ClarifyInput(BaseModel):
    ticket_text: str
    category: str | None = None
    confidence: float = 0.0
    kb_candidates: list[KBCandidate] = []
    reply_format: Literal["chat", "email"] = "chat"
    customer_name: str | None = None
    # Set by graph._reply_context: KB topics that matched words but are
    # specific to something the customer hasn't mentioned (never grounding),
    # what the customer has told us (product area, picked category), and
    # whether the product area is known (chat filter's fallback question).
    unconfirmed_topics: list[str] = []
    customer_details: str = ""
    subject_known: bool = True
    subject: str | None = None
    # No symptom described yet ("I have an issue"): one open question,
    # no grounding (chat_response.open_question).
    vague: bool = False
    # The AI's last replies in this conversation (repeat guard) and the
    # customer's latest message (answered first when it asks a question).
    recent_ai_replies: list[str] = []
    latest_message: str = ""
    # A how-to request (backend/request_kind.py): no troubleshooting
    # boilerplate. error_reported: the customer mentioned an error, so a
    # reply may ask for the exact error text (never otherwise).
    how_to: bool = False
    error_reported: bool = True
    # ACCOUNT/DATA below the stricter bar: one question to pin down what
    # the customer means, then the ticket (graph.decide_route).
    high_risk: bool = False


class ChatReply(BaseModel):
    text: str = _text(8000)


class ContinuationInput(BaseModel):
    message: str
    prior_ai_response: str


class ContinuationVerdict(BaseModel):
    is_continuation: bool = False


# ---------------------------------------------------------------------------
# summarize_conversation / summarize_ticket / suggest_steps
# ---------------------------------------------------------------------------
class ChatResolutionSummary(BaseModel):
    """Final summary of a chat the customer confirmed as resolved."""

    problem: str = _text()
    troubleshooting: list[str] = _items()
    solution: str = _text()
    # "fallback" = built without the model (provider down or invalid
    # output); reviewers should read the transcript instead.
    source: Source = "ai"


class HandoffSummary(BaseModel):
    """Brief for the technician who picks up an escalated chat or ticket."""

    issue: str = _text()
    tried: list[str] = _items()
    findings: list[str] = _items()
    unresolved_questions: list[str] = _items()
    source: Source = "ai"

    def as_text(self, steps: list[str]) -> str:
        """Plain-text form, appended to ticket_text so the queue shows it."""
        lines = [f"Issue: {self.issue}"]
        for title, items in (
            ("Already tried", self.tried),
            ("Findings", self.findings),
            ("Unresolved questions", self.unresolved_questions),
            ("Suggested next steps", steps),
        ):
            if items:
                lines.append(f"{title}:")
                lines.extend(f"- {item}" for item in items)
        return "\n".join(lines)


class SuggestStepsInput(BaseModel):
    summary: HandoffSummary
    category: str | None = None
    kb_candidates: list[KBCandidate] = []


class SuggestedSteps(BaseModel):
    steps: list[str] = Field(min_length=1, max_length=8)


# ---------------------------------------------------------------------------
# correlate_incidents / summarize_incident
# ---------------------------------------------------------------------------
class CorrelationTicket(BaseModel):
    """One candidate ticket, as the model sees it. Customers are
    pseudonymous references (no names or emails) and only the public
    conversation is included — never internal notes."""

    ticket_id: str
    customer_ref: str
    created_at: str
    category: str | None = None
    subject: str
    details: str = Field(max_length=3000)


class DepartmentOption(BaseModel):
    name: str
    categories: list[str]


class CorrelateInput(BaseModel):
    tickets: list[CorrelationTicket] = Field(min_length=2, max_length=40)
    departments: list[DepartmentOption] = []
    window_hours: int


class CorrelationJudgement(BaseModel):
    """The model's judgement on one candidate group. Facts and hypotheses
    are kept apart; a shared cause is only claimed with evidence."""

    is_related: bool
    related_ticket_ids: list[str] = _items(40)
    title: str = Field(default="Possible related reports", max_length=120)
    # Required either way: why they may be related, or why not.
    why_related: str = _text()
    common_symptoms: list[str] = _items()
    affected_services: list[str] = _items()
    observed_facts: list[str] = _items()
    hypotheses: list[str] = _items()
    possible_shared_cause: str = Field(default="Requires further investigation", max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_reasons: list[str] = _items()
    suggested_next_steps: list[str] = _items()
    candidate_departments: list[str] = _items(10)


class SummarizeIncidentInput(BaseModel):
    title: str
    tickets: list[CorrelationTicket] = Field(min_length=1, max_length=40)
    observed_facts: list[str] = []
    hypotheses: list[str] = []


class IncidentSummary(BaseModel):
    title: str = _text(120)
    summary: str = _text()
    common_symptoms: list[str] = _items()
    affected_services: list[str] = _items()
    suggested_next_steps: list[str] = _items()


# ---------------------------------------------------------------------------
# draft_post_incident
# ---------------------------------------------------------------------------
class PostIncidentFacts(BaseModel):
    """Everything the model may use: the confirmed incident's own analysis
    and what staff entered when resolving it. No customer identities, no
    ticket text, and the times are only shown for context — code writes
    the "When" and "Cause" lines itself."""

    title: str
    category: str | None = None
    started_at_ist: str
    resolved_at_ist: str
    common_symptoms: list[str] = []
    affected_services: list[str] = []
    observed_facts: list[str] = []
    resolution_note: str
    root_cause: str | None = None
    affected_customer_count: int
    affected_ticket_count: int


class PostIncidentDraft(BaseModel):
    """Model output. The customer summary is assembled from these by code
    (with the times and cause added verbatim), so the model never writes a
    time, a date or a cause."""

    what_happened: str = _text(1200)
    what_was_fixed: str = _text(1200)
    what_customers_should_do: str = _text(800)
    internal_summary: str = _text(1500)


# ---------------------------------------------------------------------------
# incident_question
# ---------------------------------------------------------------------------
class IncidentQuestionInput(BaseModel):
    message: str
    now_ist: str          # ISO 8601 with +05:30
    memory_days: int


class IncidentQuestion(BaseModel):
    """Is the customer asking whether there was/is a known problem, and if
    so for which time window (absolute, with offset) and topic?"""

    is_incident_question: bool
    window_start: datetime | None = None
    window_end: datetime | None = None
    category: Category | None = None
    topic: str | None = Field(default=None, max_length=200)


# ---------------------------------------------------------------------------
# draft_kb_entries (kb_ingester/drafting.py checks every field afterwards)
# ---------------------------------------------------------------------------
TermKind = Literal["module", "variant", "platform", "integration", "edition"]
_Short = Annotated[str, Field(min_length=1, max_length=200)]
_Label = Annotated[str, Field(min_length=1, max_length=41)]


class DraftInput(BaseModel):
    chunk_text: str
    heading_path: str = ""
    page_title: str = ""
    known_terms: list[dict] = []  # {label, kind, aliases}
    # The section's numbered procedures, read by code (kb_ingester/steps.py).
    procedures: list[list[str]] = []
    # Code found a reference table or parameter list (steps.is_reference).
    reference: bool = False


class DraftStep(BaseModel):
    text: str = _text(400)
    # Empty or not a passage of the chunk: the step is dropped by code. For
    # a procedure's steps code sets it to the item rewritten (models often
    # copy the item, which can be long: a loose cap, the 500 is checked by
    # kb_ingester/checks.py).
    quote: str = Field(default="", max_length=4000)


class DraftEntry(BaseModel):
    title: str = _text(120)
    questions: list[_Short] = Field(min_length=1, max_length=6)
    answer: str = Field(default="", max_length=1500)
    kind: Literal["how-to", "troubleshooting", "reference"]
    # Set when the entry rewrites procedure N of the ordered_steps block:
    # then it has exactly one step per item, in order.
    procedure: int | None = Field(default=None, ge=1, le=20)
    steps: list[DraftStep] = _items(40)
    applies_to: list[_Label] = _items(5)
    category: Category
    new_category: str | None = Field(default=None, max_length=41)


class ProposedTerm(BaseModel):
    label: _Label
    kind: TermKind
    aliases: list[_Label] = _items(5)
    evidence_quote: str = Field(default="", max_length=400)


class ProposedCategory(BaseModel):
    # Checked by code (categories.problem): a bad name drops this proposal
    # only, not the whole draft.
    name: str = Field(min_length=1, max_length=41)
    label: str = _text(60)
    description: str = Field(default="", max_length=200)


class DraftedEntries(BaseModel):
    entries: list[DraftEntry] = _items(12)  # 6 asked for; extras trimmed by code
    # Required (may be empty): models left it out when it was optional.
    proposed_terms: list[ProposedTerm] = Field(max_length=8)
    proposed_categories: list[ProposedCategory] = _items(2)


class StepToCheck(BaseModel):
    id: int
    step: str
    quote: str


class StepVerdict(BaseModel):
    id: int
    supported: bool


class StepSupport(BaseModel):
    verdicts: list[StepVerdict] = _items(60)
