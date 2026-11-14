"""LangGraph pipeline: fetch_customer_history -> retrieve_kb_candidates ->
classify_ticket -> decide_route -> {generate_response |
ask_clarifying_question | human_queue}.

Routing policy: thresholds, high-risk categories, escalation language
tags and clarifying rounds (app_settings "routing"), applied to a live LLM
classification grounded in KB retrieval.

retrieve_kb_candidates (backend/kb_retrieval.py) scores the ticket text
against the approved KB entries before classification even runs, so classify_ticket,
ask_clarifying_question, and generate_response are all grounded in the
same retrieved evidence instead of each guessing independently — a
strong direct KB match raises classify_ticket's confidence past a
conservative raw LLM score, and a genuine multi-candidate ambiguity
gets named specifically in ask_clarifying_question's prompt instead of
a free-floating question about categories that don't exist.

A chat follow-up to an already-resolved ticket does NOT always re-enter
this graph at classify_ticket: backend/main.py's ticket_chat first
checks is_closing_acknowledgment (a bare "thanks" closes the ticket,
see backend/closing_ack.py) and then is_continuation_of_prior_response
(does the new message refer back to the agent's own last reply, e.g.
"what's the difference" after an explanation?) — a short follow-up
fragment has almost no standalone content for classify_ticket to judge
confidently, which used to collapse decide_route's confidence and
escalate an on-topic question the conversation already answers. A
continuation calls generate_response directly (with
retrieve_kb_candidates_for_continuation grounding on the customer's own
messages in the conversation, never the AI's replies), skipping classify_ticket/decide_route for
that turn entirely. Only a genuinely new/different message falls
through to the normal classify_ticket -> decide_route path below.

Model calls live in backend/ai_service (one module per operation, with
validated pydantic input/output); the nodes here build those inputs and
apply the routing policy. A provider failure raises AIError out of the
graph, and every caller treats that as "the AI is unavailable" without
changing ticket or chat state.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph
from typing_extensions import NotRequired

from backend import app_settings, categories, db, email_utils, kb_retrieval, product, request_kind, topic_terms
from backend.ai_service import categorize_ticket as categorize_op
from backend.ai_service import AIError, chat_response, grounding, rewrite_query
from backend.ai_service.schemas import (
    AnswerInput,
    CategorizeInput,
    ClarifyInput,
    ContinuationInput,
    HistoryItem,
    KBCandidate,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routing config
# ---------------------------------------------------------------------------
# Thresholds, high-risk categories, escalation language tags and the
# clarification limit are admin-editable: app_settings.get("routing")
# (defaults: 75% base bar, 90% for ACCOUNT/BILLING/DATA, all three language
# tags, 3 clarifying rounds). Read on every decision, so a saved change
# applies to the next message. The categories themselves are data
# (backend/categories.py).

HISTORY_LOOKBACK = 5

# classify_ticket's raw LLM-reported confidence is often too conservative
# for short, common phrasings ("help with leave requests") against
# this taxonomy the model has never seen examples of. When KB retrieval
# (backend/kb_retrieval.py) finds a strong direct match, that grounded
# evidence is used to raise confidence instead of trusting the bare LLM
# number — mapped linearly from kb_retrieval.STRONG_MATCH_SCORE (treated
# as "just clears the base confidence bar") up to a near-1.0 ceiling for
# a near-exact match.
_KB_CONFIDENCE_FLOOR = 0.78
_KB_CONFIDENCE_CEILING = 0.97
_KB_CONFIDENCE_SLOPE = 0.5


def _kb_grounded_confidence(score: float) -> float:
    return min(
        _KB_CONFIDENCE_CEILING,
        _KB_CONFIDENCE_FLOOR + (score - kb_retrieval.STRONG_MATCH_SCORE) * _KB_CONFIDENCE_SLOPE,
    )

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class TicketState(TypedDict):
    ticket_id: str
    customer_id: str
    channel: str
    ticket_text: str

    customer_history: NotRequired[list[dict]]

    kb_candidates: NotRequired[list[dict]]
    # retrieve_kb_candidates: the query in the KB's words when the customer's
    # own found nothing; it counts as the customer's words for the subject checks.
    query_rewrite: NotRequired[str | None]

    category: NotRequired[str]
    confidence: NotRequired[float]
    language_tags: NotRequired[list[str]]
    clarification_attempts: NotRequired[int]

    # True when this generate_response call is answering a follow-up
    # continuation of an already-resolved ticket (see
    # is_continuation_of_prior_response) rather than a fresh classify_
    # ticket/decide_route "ai" resolution -- tweaks the prompt to treat
    # the transcript as an ongoing exchange it should build on.
    continuation: NotRequired[bool]

    # "email" for ticket-type requests (raised via the form, answered in
    # an email-style thread): the reply is wrapped in a fixed greeting/
    # closing/signature addressed to customer_name (ai_service.chat_response).
    # Absent/"chat" keeps the conversational chat reply.
    reply_format: NotRequired[Literal["chat", "email"]]
    customer_name: NotRequired[str]

    # The category the customer picked when starting the chat or raising
    # the ticket (optional). Context for the answer and a narrower KB
    # search for its grounding only: never used to classify or route, so
    # picking a category can't get a request past the high-risk bar.
    requested_category: NotRequired[str | None]

    # The AI's last replies in this conversation, newest last: a reply
    # (near-)identical to one of them is regenerated or replaced
    # (chat_response repeat guard).
    recent_ai_replies: NotRequired[list[str]]

    # The AI has answered in this conversation (the chat's / ticket's
    # last_route is "ai"). A greeting, a clarifying question or a ticket
    # notice is not an answer: "not loading" after "Hi!" is a first report,
    # not a report that an answer failed.
    answered: NotRequired[bool]

    route: NotRequired[Literal["ai", "human", "clarify"]]
    route_reason: NotRequired[str]

    ai_response: NotRequired[str]
    # Set by generate_response when the reply was grounded on an
    # "escalate_with_info" KB entry ({kb_entry_id, collect}), or when a
    # how-to request has no KB entry at all ({reason: "kb_no_match"}): the
    # caller raises the ticket in the same turn (chats._decide, main.py;
    # handoff_reason gives the reason key).
    needs_info: NotRequired[dict | None]


# ---------------------------------------------------------------------------
# language tags: decide_route's hard override. Taken from the customer's
# latest message only (never the bot's lines or older turns).
# ---------------------------------------------------------------------------
# Abuse, not frustration: "useless" or "terrible" with a real question is
# answered (politely); the chat eval found every frustrated question handed off.
_PROFANITY_WORDS = {"shit", "fuck", "fucking", "bullshit", "crap", "bastard", "idiot", "stupid", "damn"}
# The customer says the answer didn't work ("still not working", "didn't
# help"): a person takes over. Only after an AI reply: "isn't working" in a
# first report is the problem itself, and "not sure" is no failure.
_ANSWER_FAILED = re.compile(
    r"\b(?:didn'?t|did not|doesn'?t|does not|isn'?t|is not|not|never|still|no longer)\b(?:\s+\w+){0,3}?\s+"
    r"(?:work|works|working|worked|help|helped|helping|fix|fixed|solve|solved|resolve|resolved|load|loading"
    r"|show|showing|appear|appearing)\b", re.IGNORECASE)
# "still getting the same error", "the error persists": the answer didn't help either.
_STILL_FAILING = re.compile(r"\b(?:still|persists?|persisting|same (?:error|issue|problem|message))\b",
                            re.IGNORECASE)
def _detect_language_tags(ticket_text: str, answered: bool) -> list[str]:
    """offensive_language (abuse) and negation (an AI answer didn't work).
    coordinated_syntax is no longer detected: a long message with "and" and
    "but" is a normal report, and it used to hand off every one of them."""
    messages = _customer_messages(ticket_text)
    latest = messages[-1] if messages else ""
    return _tags(latest, after_answer=answered)


def _tags(message: str, after_answer: bool) -> list[str]:
    tags = []
    if set(re.findall(r"[a-z']+", message.lower())) & _PROFANITY_WORDS:
        tags.append("offensive_language")
    if after_answer and (_ANSWER_FAILED.search(message) or _STILL_FAILING.search(message)):
        tags.append("negation")
    return tags


def has_escalation_language(text: str) -> bool:
    """True if a follow-up to an AI answer (`text`, the customer's message)
    trips one of decide_route's hard-override language tags. Used by the
    follow-up gate so the continuation shortcut never bypasses the
    override: "thanks, but it's still not working" is on topic, but the
    answer failed and a person must take over."""
    return bool(set(_tags(text, after_answer=True)) & set(app_settings.get("routing").escalation_language_tags))


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def fetch_customer_history(state: TicketState) -> dict:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT ticket_text, category, status FROM tickets "
            "WHERE customer_id = ? ORDER BY created_at DESC LIMIT ?",
            (state["customer_id"], HISTORY_LOOKBACK),
        ).fetchall()
        history = [dict(row) for row in rows]
    finally:
        conn.close()
    return {"customer_history": history}


# A multi-turn ticket_text is a transcript built by main.py's
# _build_transcript ("Customer: ...\nAgent (AI): ...\n..."). Only the
# customer's own words are useful as a KB search query — the AI's own
# (possibly already off-track) questions are noise that measurably
# drags retrieval toward the wrong candidates once concatenated in.
# A speaker label starts a new message; lines without one continue the
# current message (a multi-line customer message, or an AI reply's steps).
_SPEAKER_RE = re.compile(r"^(Customer|Agent \(AI\)|ai|staff|system|technician|manager|admin):\s?(.*)$")


def _customer_messages(ticket_text: str) -> list[str]:
    """The customer's own messages of a transcript, oldest first, every
    line of each; nothing the AI or staff wrote. Plain ticket text (no
    speaker labels) is one message."""
    messages, speaker, labelled = [], None, False
    for line in ticket_text.splitlines():
        match = _SPEAKER_RE.match(line)
        if match:
            labelled, speaker, line = True, match.group(1), match.group(2)
            if speaker == "Customer":
                messages.append([])
        if speaker == "Customer" and messages:
            messages[-1].append(line)
    if not labelled:
        return [ticket_text] if ticket_text.strip() else []
    return [m for m in ("\n".join(lines).strip() for lines in messages) if m]


def _customer_authored_text(ticket_text: str) -> str:
    """All of the customer's own messages as one text (see _customer_messages)."""
    return "\n".join(_customer_messages(ticket_text))


customer_authored_text = _customer_authored_text  # public: the hand-off brief uses it


# Words that say there is a problem without saying what it is. A customer
# whose messages hold nothing else ("I have an issue", "help", "it's not
# working") hasn't described a symptom yet.
# The product's own name is vague too ("an issue with <product>").
VAGUE_WORDS = frozenset("""
    issue issues problem problems facing face faced having trouble troubles query question
    questions support something anything everything app application product software tool
    wrong working work works worked hi hello hey regarding concern concerns assistance assist
    kindly urgent asap team trying attempting
""".split())
# A latest message with fewer informative words than this is short: earlier
# customer messages are added to the KB search for context.
SHORT_MESSAGE_WORDS = 4
# KB stopwords that still state a task ("adding a user").
TASK_WORDS = frozenset({"add", "adding"})


def informative_words(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    vague = VAGUE_WORDS | product.name_words()
    return [w for w in words if (w in TASK_WORDS or w not in kb_retrieval._STOPWORDS) and w not in vague]


def is_vague(ticket_text: str) -> bool:
    """True when nothing the customer wrote describes a symptom or task."""
    return not informative_words(_customer_authored_text(ticket_text))


def retrieval_query(ticket_text: str) -> str:
    """The KB search text: the customer's latest message first. Earlier
    customer messages are added only when the latest is short or vague
    (and the latest then counts twice), so a clear new question isn't
    pulled back to an older topic, and a short follow-up ("on Linux")
    still has its context. Never the AI's own replies."""
    messages = _customer_messages(ticket_text)
    if not messages:
        return ""
    latest = messages[-1]
    if len(informative_words(latest)) >= SHORT_MESSAGE_WORDS or len(messages) == 1:
        return latest
    return "\n".join([latest, latest, *reversed(messages[:-1])])


def _kb_candidates_to_dicts(candidates: list[kb_retrieval.KBCandidate]) -> list[dict]:
    return [
        {
            "kb_entry_id": c.entry.kb_entry_id,
            "category": c.entry.category,
            "intent": c.entry.intent,
            "instruction": c.entry.instruction,
            "response": c.entry.response,
            "score": round(c.score, 3),
            "handling": c.entry.handling,
            "collect": list(c.entry.collect),
            "kind": c.entry.kind,
            "applies_to": list(c.entry.applies_to),
            "snippets": list(c.entry.snippets),
            "source_url": c.entry.source_url,
            "source_licence": c.entry.source_licence,
        }
        for c in candidates
    ]


def is_how_to(ticket_text: str) -> bool:
    """The customer wants to add, set up or configure something, with no
    sign of a fault (backend/request_kind.py), judged on the same text the
    KB search uses (the latest message, with earlier ones when it is short).
    An answer to the AI's one how-to question ("a website", "not sure")
    is still that how-to, unless it now reports a fault."""
    if request_kind.is_how_to(retrieval_query(ticket_text)):
        return True
    if asked_how_to_question(ticket_text):
        messages = _customer_messages(ticket_text)
        latest = messages[-1] if messages else ""
        return request_kind.is_unsure(latest) or not request_kind.is_fault(latest)
    return False


def error_reported(ticket_text: str) -> bool:
    """The customer mentioned an error somewhere in their messages: only
    then may a reply ask for the exact error message."""
    return request_kind.error_reported(_customer_authored_text(ticket_text))


def retrieve_kb_candidates(state: TicketState) -> dict:
    """Runs before classify_ticket so classification, clarification, and
    response generation can all be grounded in the same retrieved
    evidence instead of each guessing independently. See
    backend/kb_retrieval.py. A how-to request is never matched to a
    troubleshooting entry."""
    query = retrieval_query(state["ticket_text"])
    how_to = is_how_to(state["ticket_text"])
    candidates = kb_retrieval.retrieve_candidates(query, top_k=3, skip_faults=how_to)
    used = None
    weak = not candidates or candidates[0].score < kb_retrieval.STRONG_MATCH_SCORE
    if weak and not is_vague(state["ticket_text"]) and kb_retrieval.entry_count():
        # Nothing close in the customer's words (or only a weak match, which can be the
        # wrong entry): once more in the KB's own words, kept only if it matches better.
        try:
            rewrite = rewrite_query.rewrite_query(query, kb_retrieval.topics())
        except AIError:
            rewrite = ""
        again = (kb_retrieval.retrieve_candidates(rewrite, top_k=3, skip_faults=how_to, titles=True)
                 if rewrite else [])
        if again and (not candidates or again[0].score > candidates[0].score):
            candidates, used = again, rewrite
    found = {"kb_candidates": _kb_candidates_to_dicts(candidates)}
    return {**found, "query_rewrite": used} if used else found


def kb_candidates_for(text: str, top_k: int = 3, category: str | None = None,
                      skip_faults: bool = False) -> list[dict]:
    """KB retrieval for arbitrary text (e.g. grounding a technician's
    suggested next steps in the hand-off brief)."""
    return _kb_candidates_to_dicts(kb_retrieval.retrieve_candidates(
        text, top_k=top_k, category=category, skip_faults=skip_faults))


# A KB entry grounds a how-to answer or a technician's suggested steps
# only if it shares at least half of the customer's informative words, and
# at least this many when there are three or more: "unable to login after changing
# the plan" shares only "plan" with the change-plan entry: no evidence.
MIN_SHARED_WORDS = 2


def _stems(words) -> set[str]:
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words}


def _object_words(text: str) -> set[str]:
    return _stems(w for w in informative_words(text) if w not in request_kind.TASK_WORDS)


def shares_customer_words(candidate: dict, customer_text: str) -> bool:
    """The entry shares half of the customer's informative words, and at
    least MIN_SHARED_WORDS of three or more, task verbs ("add", "set up")
    aside."""
    customer = _object_words(customer_text)
    needed = min(MIN_SHARED_WORDS, (len(customer) + 1) // 2)
    entry = _object_words(f"{candidate['instruction']} {candidate['response']}")
    return bool(needed) and len(customer & entry) >= needed


def _main_subject(customer_text: str) -> str | None:
    """What a how-to is about: the first word, task verbs and filler aside,
    of the customer's latest line that has one ("generate a REPORT for
    attendance of last month", "submit an EXPENSE claim for my trip").
    "Not sure" lines are skipped."""
    for line in reversed(customer_text.splitlines()):
        if request_kind.is_unsure(line):
            continue
        words = [w for w in informative_words(line)
                 if w not in request_kind.TASK_WORDS and w not in GENERIC_HOW_TO_WORDS]
        if words:
            return next(iter(_stems(words[:1])))
    return None


def on_customer_subject(candidate: dict, customer_text: str) -> bool:
    """A how-to entry is on the customer's subject when it shares half of
    their words (shares_customer_words), or when it is a strong match
    (kb_retrieval.STRONG_MATCH_SCORE) whose question names the customer's
    main subject (_main_subject). Natural extra words ("for attendance of
    last month") then don't hide an entry about the same task, while "a
    leave report for my team" isn't answered by the apply-for-leave entry
    on "leave" alone."""
    if shares_customer_words(candidate, customer_text):
        return True
    question = _object_words(candidate["instruction"])
    return (candidate.get("score", 0.0) >= kb_retrieval.STRONG_MATCH_SCORE
            and _main_subject(customer_text) in question)


# Verbs that name the task itself: a guide on applying for leave doesn't
# answer "can I change my leave dates" (chat eval: the bot invented "you can
# edit the dates"). Same-task verbs share a group; generic verbs (get, do,
# see, open) are no task.
_TASK_VERB_GROUPS = ["change edit modify update amend", "delete remove", "cancel withdraw", "add create new",
                     "apply request", "clear empty", "install", "uninstall", "export download", "import upload", "reset",
                     "upgrade", "enable", "disable", "connect integrate link", "disconnect unlink", "attach",
                     "approve", "reject decline", "transfer move", "rename", "restore", "extend", "merge"]
_TASK_VERB = {grounding._verb(w): n for n, group in enumerate(_TASK_VERB_GROUPS) for w in group.split()}


def _task_groups(text: str) -> list[int]:
    return [_TASK_VERB[v] for v in map(grounding._verb, re.findall(r"[a-z]+", text.lower())) if v in _TASK_VERB]


def does_the_task(candidate: dict, customer_text: str) -> bool:
    """The entry names the customer's task (their first task verb, or a same-task one)."""
    asked = _task_groups(customer_text)
    if not asked:
        return True
    entry = " ".join([candidate.get("intent") or "", candidate["instruction"], candidate.get("response") or ""])
    return asked[0] in _task_groups(entry)


def answers_how_to(candidate: dict, customer_text: str) -> bool:
    """A KB entry that can answer a how-to: about doing something (not a
    fault, not e.g. "how long are records kept"), on the customer's
    subject. An entry's own `kind` ("how-to" / "troubleshooting") beats
    the guess from its question's wording."""
    instruction = candidate["instruction"]
    kind = candidate.get("kind")
    about_a_task = (kind == "how-to" if kind else
                    not request_kind.is_fault(instruction) and request_kind.mentions_task(instruction))
    return about_a_task and on_customer_subject(candidate, customer_text) and does_the_task(candidate, customer_text)


# The AI's own how-to questions (fixed text, no model call). Asked at most
# once per conversation (asked_how_to_question); after the customer's
# answer the how-to is answered from the KB or handed off.
HOW_TO_SUBJECT_QUESTION = "What exactly do you want to {verb}, and in which part of {product}: {options}?"
HOW_TO_GENERIC_QUESTION = "What exactly do you want to {verb} in {product}?"
HOW_TO_VARIANT_QUESTION = "I have a guide for each of these: {options}. Which one is it?"
HOW_TO_ONE_VARIANT_QUESTION = "I have a guide for {option}. Is that the one you're using?"
_HOW_TO_QUESTION_STARTS = ("What exactly do you want to ", "I have a guide for ")
# Words that don't say what a how-to is about ("add a new one").
GENERIC_HOW_TO_WORDS = frozenset("new another one first more extra thing things".split())
_SET_UP = re.compile(r"\bset (?:\w+ )?up\b|\bsetup\b|\bsetting up\b|\bconfigur\w*|\binstall\w*", re.IGNORECASE)


def _ai_messages(ticket_text: str) -> list[str]:
    """The AI's replies in a transcript, every line of each."""
    messages, current = [], None
    for line in ticket_text.splitlines():
        match = _SPEAKER_RE.match(line)
        if match:
            current = [match.group(2)] if match.group(1) in ("Agent (AI)", "ai") else None
            if current is not None:
                messages.append(current)
        elif current is not None:
            current.append(line)
    return ["\n".join(m) for m in messages]


def asked_how_to_question(ticket_text: str) -> bool:
    """The AI already asked its one how-to question in this conversation
    (also inside an email-style reply, after the greeting)."""
    return any(line.strip().startswith(_HOW_TO_QUESTION_STARTS)
               for message in _ai_messages(ticket_text) for line in message.splitlines())


def how_to_subject(state: TicketState) -> set[str]:
    """What the how-to is about: the customer's own words (task verbs
    aside), or the product areas (topic_terms) they named."""
    ticket_text = state["ticket_text"]
    words = _object_words(retrieval_query(ticket_text)) - GENERIC_HOW_TO_WORDS
    return words | set(topic_terms.subjects_mentioned(_customer_authored_text(ticket_text)))


_options = chat_response.options_text


def how_to_question(state: TicketState) -> str | None:
    """The one question a how-to needs before the KB can answer it, or
    None. No subject at all ("how do I set it up"): what exactly, and in
    which part of the product (its confirmed modules / variants). KB guides
    that apply only to something the customer hasn't named (e.g. the
    Android / iOS app guides): which one. Never asked twice, never about a
    record or an account."""
    ticket_text = state.get("ticket_text", "")
    if not ticket_text or asked_how_to_question(ticket_text):
        return None
    how_to = is_how_to(ticket_text)
    if how_to and not how_to_subject(state):
        verb = "set up" if _SET_UP.search(retrieval_query(ticket_text)) else "do"
        labels = topic_terms.subject_labels()
        if labels:
            return HOW_TO_SUBJECT_QUESTION.format(verb=verb, product=product.name(),
                                                  options=_options(labels[:6]))
        return HOW_TO_GENERIC_QUESTION.format(verb=verb, product=product.name())
    if is_vague(ticket_text):
        return None
    usable, unconfirmed = grounding_candidates(state)
    if not how_to:
        # A report: only guides on the customer's own subject (not a match on "app" alone: Slack is no
        # reason to ask Android or iOS) that stay gated after any clarifying question (a platform, an
        # edition: not a module, which the first question unlocks).
        customer = _customer_authored_text(ticket_text)
        unconfirmed = [(c, m) for c, m in unconfirmed
                       if all(topic_terms.kind_of(t) != "module" for t in m) and shares_customer_words(c, customer)]
    if usable or not unconfirmed:
        return None
    labels: list[str] = []
    for _, missing in unconfirmed:
        labels += [label for label in sorted(missing) if label not in labels]
    if len(labels) == 1 and topic_terms.kind_of(labels[0]) != "module":
        labels = topic_terms.labels_of_kind(topic_terms.kind_of(labels[0])) or labels   # the choice, not a leading yes/no
    labels = labels[:4]
    if len(labels) == 1:
        return HOW_TO_ONE_VARIANT_QUESTION.format(option=labels[0])
    return HOW_TO_VARIANT_QUESTION.format(options=_options(labels))


def handoff_kb_candidates(customer_text: str) -> list[dict]:
    """The KB entries that match what the customer wrote, for the
    technician's suggested next steps: above KB_MIN_SCORE, no topic the
    customer hasn't mentioned (topic_terms), no troubleshooting entry for
    a how-to, and enough of the customer's own words in common."""
    how_to = request_kind.is_how_to(customer_text)
    return [c for c in kb_candidates_for(customer_text, skip_faults=how_to)
            if (answers_how_to(c, customer_text) if how_to else shares_customer_words(c, customer_text))
            and not topic_terms.missing_terms(c, customer_text)]


def retrieve_kb_candidates_for_continuation(transcript: str, top_k: int = 3) -> list[dict]:
    """KB retrieval for a follow-up/continuation turn (see
    is_continuation_of_prior_response below): searches on the customer's
    own messages (retrieval_query: the latest first, earlier ones when it
    is short), never on the AI's replies. A short follow-up fragment
    ("what is the difference") has almost no topic vocabulary of its own;
    the customer's earlier messages carry the topic. Searching on the AI's
    previous reply instead fed the AI's own wording back into retrieval
    and inflated the score of whatever it had already said."""
    query = retrieval_query(transcript)
    return kb_candidates_for(query, top_k=top_k, skip_faults=request_kind.is_how_to(query))


def is_continuation_of_prior_response(message_text: str, prior_ai_response: str) -> bool:
    """Does `message_text` refer back to, ask about, elaborate on, or
    compare something in `prior_ai_response` (a continuation of the same
    thread), or is it a genuinely new request? Runs on a follow-up after an
    AI answer, before classify_ticket -- classify_ticket judges each
    message's own classifiability, and a short follow-up fragment has
    almost no standalone content to classify confidently, which used to
    collapse decide_route's confidence and wrongly escalate an on-topic
    question. A positive result skips classify_ticket/decide_route for
    this turn."""
    return chat_response.is_continuation(
        ContinuationInput(message=message_text, prior_ai_response=prior_ai_response)
    ).is_continuation


def _history(state: TicketState) -> list[HistoryItem]:
    return [HistoryItem(**h) for h in state.get("customer_history", [])]


def _candidates(state: TicketState) -> list[KBCandidate]:
    return [KBCandidate(**c) for c in state.get("kb_candidates", [])]


def classify_ticket(state: TicketState) -> dict:
    candidates = state.get("kb_candidates", [])
    raw = categorize_op.categorize_ticket(
        CategorizeInput(
            ticket_text=state["ticket_text"],
            history=_history(state),
            kb_candidates=_candidates(state),
        )
    )
    llm_category, llm_confidence = raw.category, raw.confidence

    category, confidence = llm_category, llm_confidence
    top = candidates[0] if candidates else None
    # A match specific to something the customer never mentioned (e.g. a
    # Slack entry for "approvals error") is no evidence for its category.
    if top and topic_terms.missing_terms(top, _customer_authored_text(state["ticket_text"])):
        top = None
    if top and top["score"] >= kb_retrieval.STRONG_MATCH_SCORE:
        grounded_confidence = _kb_grounded_confidence(top["score"])
        if top["category"] == llm_category:
            # Retrieval agrees with the LLM's own pick and found a strong
            # direct match — trust it over a conservative raw confidence
            # number for a short/common phrasing.
            confidence = max(confidence, grounded_confidence)
        elif llm_confidence < app_settings.get("routing").confidence_threshold \
                and top["category"] in categories.names():
            # LLM was unsure AND retrieval strongly points elsewhere —
            # trust the grounded KB match over an ungrounded guess. Only
            # to a confirmed category.
            category, confidence = top["category"], grounded_confidence

    print(
        f"[classify_ticket] llm_category={llm_category!r} "
        f"llm_confidence={llm_confidence:.2f} -> category={category!r} "
        f"confidence={confidence:.2f} "
        f"(top_kb_match={top['intent'] if top else None}, "
        f"score={top['score'] if top else None})"
    )

    return {
        "category": category,
        "confidence": confidence,
        "language_tags": _detect_language_tags(state["ticket_text"], bool(state.get("answered"))),
    }


def _info_entry(state: TicketState) -> dict | None:
    """The top usable KB candidate when it is an "escalate_with_info"
    entry with an answer (its steps, collect list and safety note are the
    reply, and the ticket is raised in the same turn)."""
    if not state.get("ticket_text") or is_vague(state["ticket_text"]):
        return None
    usable, _ = grounding_candidates(state)
    top = usable[0] if usable else None
    return top if top and top.get("handling") == "escalate_with_info" and top.get("response", "").strip() else None


def decide_route(state: TicketState) -> dict:
    confidence = state["confidence"]
    category = state["category"]
    tags = set(state.get("language_tags", []))
    clarification_attempts = state.get("clarification_attempts", 0)
    ticket_text = state.get("ticket_text", "")
    how_to = bool(ticket_text) and is_how_to(ticket_text)

    policy = app_settings.get("routing")
    max_attempts = policy.max_clarification_attempts
    triggered_tags = tags & set(policy.escalation_language_tags)
    high_risk_below_bar = (
        category in policy.high_risk_categories
        and confidence < policy.high_risk_confidence_threshold
    )
    below_base_bar = confidence < policy.confidence_threshold

    if triggered_tags:
        # Hard override: fires immediately regardless of confidence, category,
        # or how many clarification rounds have already happened.
        route, reason = "human", (
            f"escalation language tag(s) present: {sorted(triggered_tags)}"
        )
        clarification_attempts_out = clarification_attempts
    elif how_to and how_to_question(state):
        # "How do I set it up?" names nothing, or the KB's guides apply only
        # to something not named yet (the Android / iOS app):
        # ONE fixed question, no ticket yet. The answer is then answered
        # from the KB or handed off (never asked again).
        route, reason = "clarify", (
            "how-to that needs one detail before the KB can answer it "
            "(what exactly, or which of the KB's guides): one question, then the KB or a ticket"
        )
        clarification_attempts_out = clarification_attempts + 1
    elif high_risk_below_bar and _info_entry(state):
        # The KB says what support needs for this: its steps, collect list
        # and safety note are the reply, and the ticket is raised in the
        # same turn (generate_response -> needs_info).
        route, reason = "ai", (
            f"high-risk category {category!r} below its bar, but the matching KB "
            "entry is escalate_with_info: its steps and collect list, then a ticket"
        )
        clarification_attempts_out = clarification_attempts
    elif high_risk_below_bar and clarification_attempts == 0 and (not how_to or vague_task(ticket_text)) \
            and not error_reported(ticket_text) and ticket_text and not is_vague(ticket_text):
        # A vague first report ("unable to login after changing the plan"):
        # ONE question to pin down what the customer means (which login,
        # what they see), then the ticket. The AI never answers or
        # suggests causes on account/billing/data (ask_clarifying_question with
        # high_risk); the next turn still below the bar goes to a human.
        route, reason = "clarify", (
            f"high-risk category {category!r} requires confidence >= "
            f"{policy.high_risk_confidence_threshold}, got {confidence:.2f} — one "
            "clarifying question on the first message, then a human"
        )
        clarification_attempts_out = clarification_attempts + 1
    elif high_risk_below_bar:
        # Account, billing and data ambiguity goes to a human:
        # a clear request, a reported error, or the answer to the one
        # clarifying question. The AI never keeps guessing here.
        route, reason = "human", (
            f"high-risk category {category!r} requires confidence >= "
            f"{policy.high_risk_confidence_threshold}, got {confidence:.2f} — "
            "escalating, no further clarification for account/billing/data risk"
        )
        clarification_attempts_out = clarification_attempts
    elif not how_to and how_to_question(state):
        # A report the KB's guides cover only for something not named yet (the Android / iOS
        # app): the same ONE fixed question as for a how-to, not a model-written one.
        route, reason = "clarify", (
            "the KB's guides on this apply to something the customer hasn't named: one fixed question, "
            "then the KB or a ticket"
        )
        clarification_attempts_out = clarification_attempts + 1
    elif below_base_bar and how_to:
        # "How do I add X?" is clear (or its one question was answered):
        # answer it from the KB, or say there's no guide and hand off
        # (generate_response). Never "are you referring to...?".
        route, reason = "ai", (
            f"confidence {confidence:.2f} for category {category!r} is below the bar, "
            "but a how-to request is clear: answer from the KB or hand off, no clarifying question"
        )
        clarification_attempts_out = clarification_attempts
    elif below_base_bar and clarification_attempts < max_attempts:
        route, reason = "clarify", (
            f"confidence {confidence:.2f} for category {category!r} is below the "
            f"required bar (clarification attempt "
            f"{clarification_attempts + 1}/{max_attempts})"
        )
        clarification_attempts_out = clarification_attempts + 1
    elif below_base_bar:
        # The questions are used up: answer from the KB entry that matches,
        # or say there is no guide and raise a ticket (generate_response).
        route, reason = "ai", (
            f"still below the confidence bar after {max_attempts} "
            f"clarification attempts (confidence {confidence:.2f}, category "
            f"{category!r}): answer from the KB, or no guide and a ticket"
        )
        clarification_attempts_out = clarification_attempts
    elif not how_to and ticket_text and not is_vague(ticket_text) and not grounding_candidates(state)[0]:
        # A fault report no KB entry covers: never answered from general
        # knowledge. Clarifying questions (the answers may match an entry),
        # then generate_response says there is no guide and hands off.
        if clarification_attempts < max_attempts:
            route, reason = "clarify", (
                "no KB entry covers this report: a clarifying question "
                f"(attempt {clarification_attempts + 1}/{max_attempts}), never an answer from general knowledge"
            )
            clarification_attempts_out = clarification_attempts + 1
        else:
            route, reason = "ai", "no KB entry covers this report after the clarifying rounds: no guide, a ticket"
            clarification_attempts_out = clarification_attempts
    else:
        route, reason = "ai", (
            f"confidence {confidence:.2f} sufficient for category {category!r}"
        )
        clarification_attempts_out = clarification_attempts

    return {
        "route": route,
        "route_reason": reason,
        "clarification_attempts": clarification_attempts_out,
    }


def route_after_decide(state: TicketState) -> str:
    return {
        "ai": "generate_response",
        "clarify": "ask_clarifying_question",
    }.get(state["route"], "human_queue")


_ONE_VARIANT = re.compile(HOW_TO_ONE_VARIANT_QUESTION.format(option="(.+)").replace("?", r"\?"))


def _confirmed_variant(ticket_text: str) -> str:
    """"I have a guide for Android. Is that the one you're using?" answered "yes": the option
    ("\nAndroid"), else nothing."""
    asked = (_ai_messages(ticket_text) or [""])[-1].strip()
    match = _ONE_VARIANT.fullmatch(asked)
    return f"\n{match.group(1)}" if match and request_kind.is_affirmative((_customer_messages(ticket_text) or [""])[-1]) else ""


def grounding_candidates(state: TicketState) -> tuple[list[dict], list[tuple[dict, set[str]]]]:
    """The KB candidates an answer or clarifying question may rely on, and
    the ones it may not: (usable, [(candidate, terms the customer hasn't
    mentioned)]). With a customer-picked category the search is narrowed
    to that category when it has a close match there, and an entry of the
    picked category counts as confirmed (the customer chose that topic).
    An entry about another variant than the one named (the Android guide
    for an iPad app) is neither."""
    # The rewrite first: in the KB's words it names the task (does_the_task reads the first one).
    customer_text = f"{state.get('query_rewrite') or ''}\n{_customer_authored_text(state['ticket_text'])}".strip()
    customer_text += _confirmed_variant(state["ticket_text"])
    candidates = state.get("kb_candidates", [])
    requested = state.get("requested_category")
    how_to = is_how_to(state["ticket_text"])
    if requested in categories.names():
        narrowed = kb_candidates_for(retrieval_query(state["ticket_text"]), category=requested,
                                     skip_faults=how_to)
        if narrowed:
            candidates = narrowed
    if how_to:  # a how-to is answered only by an entry about doing that task
        candidates = [c for c in candidates if answers_how_to(c, customer_text)]
        # Reviewed guides (kind "how-to", numbered steps from a help page)
        # before the generic canonical advice on the same subject.
        candidates.sort(key=lambda c: c.get("kind") != "how-to")
    # The one clarifying question was asked: an entry held back only because
    # the customer didn't name its module is used now (they may never use the
    # KB's own word for it). Platforms and the like still gate: the Android
    # guide never answers an iPad question.
    asked = state.get("clarification_attempts", 0) >= app_settings.get("routing").max_clarification_attempts
    usable, unconfirmed = [], []
    for c in candidates:
        if topic_terms.names_another_variant(c, customer_text):
            continue
        missing = topic_terms.missing_terms(c, customer_text)
        if asked and all(topic_terms.kind_of(t) == "module" for t in missing):
            missing = set()
        if missing and c["category"] != requested:
            unconfirmed.append((c, missing))
        else:
            usable.append(c)
    return usable, unconfirmed


def _reply_context(state: TicketState) -> dict:
    """What the answer and clarify prompts get beyond the transcript. A
    customer who hasn't described a symptom yet gets no grounding at all
    (any KB match would be a guessed scenario)."""
    vague = is_vague(state["ticket_text"])
    usable, unconfirmed = ([], []) if vague else grounding_candidates(state)
    customer_text = _customer_authored_text(state["ticket_text"])
    messages = _customer_messages(state["ticket_text"])
    requested = state.get("requested_category")
    subjects = topic_terms.subjects_mentioned(customer_text)
    how_to = is_how_to(state["ticket_text"])
    # A how-to matched to a KB guide on the customer's subject (graph.
    # answers_how_to) needs no product area: the guide is the answer. A
    # product with no confirmed modules/variants has nothing to ask about.
    guided = how_to and bool(usable)
    nothing_to_ask = not topic_terms.subject_labels()
    details = [f"Product area: {', '.join(subjects)} (stated by the customer)" if subjects
               else "Product area: covered by the kb_guidance guide for this request" if guided
               else "Product area: not stated yet"]
    if requested:
        details.append(f"Category the customer picked: {requested}")
    return {
        "kb_candidates": [KBCandidate(**c) for c in usable],
        "unconfirmed_topics": [
            f'[{c["category"]} / {c["intent"]}] "{c["instruction"]}": specific to '
            f'{", ".join(sorted(missing))}, which the customer has not mentioned'
            for c, missing in unconfirmed
        ],
        "customer_details": "\n".join(details),
        "subject_known": bool(subjects) or guided or nothing_to_ask,
        "subject": subjects[0] if len(subjects) == 1 else None,
        "vague": vague,
        "recent_ai_replies": list(state.get("recent_ai_replies") or [])[-2:],
        "latest_message": messages[-1] if messages else "",
        "customer_text": customer_text,
        "how_to": how_to,
        "error_reported": error_reported(state["ticket_text"]),
    }


NO_KB_REPLY_CHAT = ("I don't have a guide for that yet, so I've raised a ticket and the support "
                    "team will reply there.")
NO_KB_REPLY_EMAIL = ("I don't have a guide for that yet, so I've passed your ticket to the support "
                     "team and they'll reply here.")


def handoff_reason(needs_info: dict | None) -> str:
    """The escalation reason key for a generate_response `needs_info`."""
    return "kb_no_match" if (needs_info or {}).get("reason") == "kb_no_match" else "kb_needs_info"


def generate_response(state: TicketState) -> dict:
    """The answer, or, when the best grounding is an "escalate_with_info"
    KB entry, numbered steps to collect what support needs plus
    `needs_info` so the caller raises the ticket in the same turn. A clear
    how-to request with no KB entry gets an honest "no article" reply (no
    model call, no improvised steps) and is handed off the same way."""
    data = AnswerInput(
        ticket_text=state["ticket_text"],
        category=state.get("category"),
        history=_history(state),
        continuation=bool(state.get("continuation")),
        reply_format=state.get("reply_format", "chat"),
        customer_name=state.get("customer_name"),
        **_reply_context(state),
    )
    top = data.kb_candidates[0] if data.kb_candidates else None
    if top is None and (off_topic := off_topic_reply(state)):
        return {"ai_response": off_topic, "needs_info": None}
    if top is None and not data.vague:
        return _no_guide(data, state)
    if top is not None and top.handling == "escalate_with_info" and top.response.strip():
        reply = chat_response.info_request(data)
        return {"ai_response": reply.text,
                "needs_info": {"kb_entry_id": top.kb_entry_id, "collect": list(top.collect)}}
    follow_up = bool(state.get("answered") and data.recent_ai_replies and data.latest_message and top is not None)
    if follow_up and request_kind.asks_for_sources(data.latest_message):
        return {"ai_response": chat_response.sources(data).text, "needs_info": None}
    steps = data.continuation and request_kind.asks_for_steps(data.latest_message) and chat_response.steps_again(data)
    if follow_up and not steps and not request_kind.asks_for_steps(data.latest_message):
        # A follow-up the guide doesn't answer: say so and offer a ticket, never a claim.
        try:
            covered = chat_response.covers_latest(data)
        except AIError:
            covered = True   # the check failed: answer as before
        if not covered:
            if chat_response.FOLLOWUP_NOT_COVERED in data.recent_ai_replies[-1:]:
                return _no_guide(data, state)   # offered once already: never the same question twice
            _note_unanswered(state, data, "followup_not_covered")
            return {"ai_response": chat_response.followup_not_covered(data).text, "needs_info": None}
    reply = steps or chat_response.answer(data)
    if reply.not_covered:
        return _no_guide(data, state)
    return {"ai_response": reply.text, "needs_info": None}


def _no_guide(data: AnswerInput, state: TicketState) -> dict:
    """No KB entry answers this (none matched, or the matched one doesn't
    cover the latest message): say so plainly and hand off, no model call,
    never an answer from general knowledge."""
    _note_unanswered(state, data, "no_guide")
    text = NO_KB_REPLY_EMAIL if data.reply_format == "email" else NO_KB_REPLY_CHAT
    if data.reply_format == "email":
        text = email_utils.format_email_reply(data.customer_name, text)
    return {"ai_response": text, "needs_info": {"kb_entry_id": None, "collect": [], "reason": "kb_no_match"}}


def _note_unanswered(state: TicketState, data: AnswerInput, reason: str) -> None:
    """Save the question for the admin's Unanswered questions list. Never
    for Try a ticket (SIM- ids: nothing is persisted), and never fails the turn."""
    conversation_id = state.get("ticket_id") or ""
    if not data.latest_message or conversation_id.startswith("SIM-"):
        return
    try:
        conn = db.get_connection()
        try:
            conn.execute(
                "INSERT INTO kb_unanswered (unanswered_id, question, channel, conversation_id, reason, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (f"UQ-{uuid.uuid4().hex[:12]}", data.latest_message[:1000], state.get("channel") or "chat",
                 conversation_id, reason, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        logger.exception("Saving an unanswered question failed")


# "I need to change something with our account": a task with no object.
_VAGUE_OBJECT = re.compile(r"\b(?:something|anything|stuff|things?|some (?:settings?|details?|info))\b", re.IGNORECASE)
HIGH_RISK_TASK_QUESTION = "What exactly do you want to {verb}?"


def vague_task(ticket_text: str) -> bool:
    latest = (_customer_messages(ticket_text) or [""])[-1]
    return is_how_to(latest) and bool(_VAGUE_OBJECT.search(latest))


def high_risk_task_question(state: TicketState) -> str:
    """The one question for a vague account/billing/data task, fixed text:
    what exactly, with the matching guide's title as an example."""
    latest = (_customer_messages(state["ticket_text"]) or [""])[-1]
    verbs = [w for w in re.findall(r"[a-z]+", latest.lower()) if grounding._verb(w) in _TASK_VERB]
    question = HIGH_RISK_TASK_QUESTION.format(verb=verbs[0] if verbs else "do")
    top = (state.get("kb_candidates") or [None])[0]
    return f"{question} For example: {top['intent']}?" if top else question


OFF_TOPIC_REPLY = ("Sorry, that's outside what I can help with: I'm the support assistant for {product}. "
                   "Is there something in {product} I can help you with?")
OFF_TOPIC_AGAIN = "I'll leave that one, sorry. Whenever you have a question about {product}, I'm here."


def off_topic_reply(state: TicketState) -> str | None:
    """A message about something else (the cricket score, a joke): the
    classifier says OTHER, no KB entry is anywhere near, and no product term
    or the product's name is in it. A fixed, brief reply, no ticket, never
    the same question twice (docs/CHAT_CONTRACT.md rule 12)."""
    latest = (_customer_messages(state["ticket_text"]) or [""])[-1]
    if state.get("category") != "OTHER" or state.get("kb_candidates") or is_how_to(latest):
        return None
    if topic_terms.mentioned(latest) or set(re.findall(r"[a-z0-9]+", latest.lower())) & product.name_words():
        return None
    name = product.name()
    asked = OFF_TOPIC_REPLY.format(product=name)
    text = OFF_TOPIC_AGAIN.format(product=name) if asked in state["ticket_text"] else asked
    if state.get("reply_format") == "email":
        text = email_utils.format_email_reply(state.get("customer_name"), text)
    return text


def ask_clarifying_question(state: TicketState) -> dict:
    """clarify branch — the ticket/transcript is too ambiguous to classify
    confidently. Asks one targeted question grounded in the actual
    candidate KB entries (e.g. which of two *real* KB topics
    applies) rather than a free-floating meta-question about categories
    that don't exist in this taxonomy. Stored via `ai_response` so it
    flows through the same message path as generate_response's output."""
    off_topic = off_topic_reply(state)
    if off_topic:
        return {"ai_response": off_topic}
    question = how_to_question(state)
    if question:  # fixed text: no model call, no record or account asked for
        if state.get("reply_format") == "email":
            question = email_utils.format_email_reply(state.get("customer_name"), question)
        return {"ai_response": question}
    policy = app_settings.get("routing")
    high_risk = (state.get("category") in policy.high_risk_categories
                 and state.get("confidence", 0.0) < policy.high_risk_confidence_threshold)
    context = _reply_context(state)
    if high_risk and vague_task(state["ticket_text"]):
        question = high_risk_task_question(state)   # fixed text, no model call
        if state.get("reply_format") == "email":
            question = email_utils.format_email_reply(state.get("customer_name"), question)
        return {"ai_response": question}
    if high_risk:
        # Account/billing/data: no KB topics to choose between and no
        # product area to ask about; one question about what the customer means.
        context.update(kb_candidates=[], unconfirmed_topics=[], subject_known=True)
    reply = chat_response.clarify(
        ClarifyInput(
            ticket_text=state["ticket_text"],
            category=state.get("category"),
            confidence=state.get("confidence", 0.0),
            reply_format=state.get("reply_format", "chat"),
            customer_name=state.get("customer_name"),
            high_risk=high_risk,
            **context,
        )
    )
    return {"ai_response": reply.text}


def human_queue(state: TicketState) -> dict:
    """No-op terminal node for the human branch — main.py persists the
    ticket with route='human', status='open', assigned_technician_id=None."""
    return {}


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------
def build_graph():
    graph = StateGraph(TicketState)

    graph.add_node("fetch_customer_history", fetch_customer_history)
    graph.add_node("retrieve_kb_candidates", retrieve_kb_candidates)
    graph.add_node("classify_ticket", classify_ticket)
    graph.add_node("decide_route", decide_route)
    graph.add_node("generate_response", generate_response)
    graph.add_node("ask_clarifying_question", ask_clarifying_question)
    graph.add_node("human_queue", human_queue)

    graph.set_entry_point("fetch_customer_history")
    graph.add_edge("fetch_customer_history", "retrieve_kb_candidates")
    graph.add_edge("retrieve_kb_candidates", "classify_ticket")
    graph.add_edge("classify_ticket", "decide_route")
    graph.add_conditional_edges(
        "decide_route",
        route_after_decide,
        {
            "generate_response": "generate_response",
            "ask_clarifying_question": "ask_clarifying_question",
            "human_queue": "human_queue",
        },
    )
    graph.add_edge("generate_response", END)
    graph.add_edge("ask_clarifying_question", END)
    graph.add_edge("human_queue", END)

    return graph.compile()
