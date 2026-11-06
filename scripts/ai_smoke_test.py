"""Run the 10 most important AI prompts against the configured provider
and report invalid JSON / weak answers. KB grounding comes from the
database's approved entries (empty on a new install: the prompts then run
without grounding). Not a unit test: it calls the
real model (AI_PROVIDER and its credentials from .env).

    AI_PROVIDER=openai_compatible .ven/bin/python scripts/ai_smoke_test.py

quickml_appsail only works while serving a request on AppSail (it uses
the credential AppSail injects), so it can't be run from a laptop; run
these prompts there instead (Phase 4 stage 2).

Prints, per prompt: OK/FAIL, seconds, attempts (a retry means the first
reply was rejected), and the parsed output. Never prints credentials.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import graph  # noqa: E402  (also loads .env via backend/__init__)
from backend.ai_service import (  # noqa: E402
    AIError, categorize_ticket, chat_response, correlate_incidents, draft_post_incident,
    incident_question, provider, suggest_steps, summarize_conversation, summarize_incident,
)
from backend.ai_service.schemas import (  # noqa: E402
    AnswerInput, CategorizeInput, ClarifyInput, ContinuationInput, CorrelateInput, CorrelationTicket,
    DepartmentOption, IncidentQuestionInput, KBCandidate, PostIncidentFacts, SuggestStepsInput,
    SummarizeIncidentInput,
)


class _Retries(logging.Handler):
    count = 0

    def emit(self, record):
        if "failed" in record.getMessage() and "validation" in record.getMessage():
            _Retries.count += 1


def kb(text):
    return [KBCandidate(**c) for c in graph.kb_candidates_for(text)]


CLOCK_IN = "Clock-in on the app shows a location error since 10:00. I allowed location already."
TRANSCRIPT = (
    "Customer: Clock-in on the app shows a location error since 10:00.\n"
    "Agent (AI): Please allow location access for the app in your phone settings.\n"
    "Customer: I allowed it, still the same error. I need a human please."
)
TICKETS = [
    CorrelationTicket(ticket_id=f"TCK-{i}", customer_ref=f"C{i}", created_at=f"2026-10-23T10:0{i}:00",
                      category=cat, subject=subj, details=det)
    for i, (cat, subj, det) in enumerate([
        ("ISSUE", "Clock-in location error", "Nobody in our office can clock in since 10:00 IST."),
        ("SETUP", "App asks for location again", "The app keeps asking for location around 10:05, allowed, no change."),
        ("ISSUE", "Clock-in fails on Android", "Clock-in shows 'location not available' at 10:02."),
    ])
]
DEPTS = [DepartmentOption(name="Product Support", categories=["ISSUE", "SETUP"])]

CASES = [
    ("1 categorize (clear)", lambda: categorize_ticket.categorize_ticket(
        CategorizeInput(ticket_text=CLOCK_IN, kb_candidates=kb(CLOCK_IN)))),
    ("2 categorize (billing, high-risk)", lambda: categorize_ticket.categorize_ticket(
        CategorizeInput(ticket_text="Please downgrade my plan and refund last month's invoice."))),
    ("3 chat answer", lambda: chat_response.answer(AnswerInput(
        ticket_text="How do I apply for leave next Friday?",
        kb_candidates=kb("apply for leave"), customer_name="Asha"))),
    ("4 clarifying question", lambda: chat_response.clarify(ClarifyInput(
        ticket_text="it is not working", kb_candidates=kb("not working")))),
    ("5 is_continuation", lambda: chat_response.is_continuation(ContinuationInput(
        message="what's the difference between the two?",
        prior_ai_response="You can apply for casual leave or for sick leave."))),
    ("6 escalation summary", lambda: summarize_conversation.summarize_escalation(
        TRANSCRIPT, "The customer asked for a human agent.")),
    ("7 suggested steps", lambda: suggest_steps.suggest_steps(SuggestStepsInput(
        summary=summarize_conversation.fallback_handoff(CLOCK_IN, "customer request"),
        category="ISSUE", kb_candidates=kb(CLOCK_IN)))),
    ("8 correlate incidents", lambda: correlate_incidents.correlate_incidents(
        CorrelateInput(tickets=TICKETS, departments=DEPTS, window_hours=12))),
    ("9 incident summary", lambda: summarize_incident.summarize_incident(SummarizeIncidentInput(
        title="Clock-in location errors", tickets=TICKETS,
        observed_facts=["3 customers report clock-in errors from 10:00"], hypotheses=["Geofence service issue"]))),
    ("10 post-incident draft", lambda: draft_post_incident.draft_post_incident(PostIncidentFacts(
        title="Clock-in location errors", category="ISSUE",
        started_at_ist="23 Oct 2026, 10:00 IST", resolved_at_ist="23 Oct 2026, 11:15 IST",
        common_symptoms=["Location error at clock-in"], affected_services=["Attendance"],
        observed_facts=["3 customers reported clock-in errors"], resolution_note="Restarted the geofence service.",
        root_cause=None, affected_customer_count=3, affected_ticket_count=3))),
    ("11 incident question", lambda: incident_question.parse_incident_question(IncidentQuestionInput(
        message="were you down yesterday around 3pm?", now_ist="2026-10-23T12:00:00+05:30",
        memory_days=90))),
]


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="  log: %(message)s")
    logging.getLogger().addHandler(_Retries())
    print(f"provider: {provider.provider_name()}\n")
    failures = 0
    for name, run in CASES:
        _Retries.count = 0
        start = time.time()
        try:
            out = run()
            status = "OK"
        except AIError as exc:
            out, status = str(exc), "FAIL"
            failures += 1
        elapsed = time.time() - start
        retry = f", {_Retries.count} rejected repl{'y' if _Retries.count == 1 else 'ies'}" if _Retries.count else ""
        print(f"[{status}] {name} ({elapsed:.1f}s{retry})")
        if hasattr(out, "model_dump"):
            out = out.model_dump()
        print("   " + (json.dumps(out, indent=2, default=str) if not isinstance(out, str) else out)
              .replace("\n", "\n   ")[:2500] + "\n")
    print(f"{len(CASES) - failures}/{len(CASES)} succeeded")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
