"""Instructions in any reply must be backed by the KB entry, never by the
customer's own words (grounding.ground_instructions, chat_response._ground).
Sentences and verdicts from the real-model chat eval's transcripts."""

from __future__ import annotations

import pytest

from backend.ai_service import chat_response, grounding, provider
from backend.ai_service.schemas import AnswerInput, KBCandidate

CLOCK_IN = ("Clock-in needs location access when your company uses geofencing.\n"
            "1. Allow location for the app in your phone settings and try again.")
ATTENDANCE = ("Attendance reports can be exported as CSV or Excel from the Reports page.\n"
              "1. Open Attendance, then Reports.\n2. Pick the date range and click Export.")


@pytest.mark.parametrize("sentence, kept", [
    ("Allow location access for the app in your phone settings and try clocking in again.", True),
    ("Have you tried restarting the app after allowing location access?", False),
    ("Did you try toggling the location services on and off again in your phone settings?", False),
    ("If it's still not working, disable the firewall.", False),
    ("Clock-in needs location when geofencing is on.", True),            # a statement, not an instruction
])
def test_an_instruction_needs_a_kb_passage_with_its_action(sentence, kept):
    assert grounding.instruction_supported(sentence, CLOCK_IN) is kept


@pytest.mark.parametrize("sentence, kept", [
    ("Choose the date range and click Export.", True),                     # pick / choose: one action
    ("Navigate to Attendance, then Reports.", True),
    ("Look for the Export button on the Reports page.", True),             # looking for what the KB names
    ("If so, try refreshing the page and attempting the export again.", False),
    ("Look for the Export button at the top or bottom of the report.", False),   # an invented place
])
def test_paraphrases_of_kb_steps_stay(sentence, kept):
    assert grounding.instruction_supported(sentence, ATTENDANCE) is kept


def _input(customer_text):
    entry = KBCandidate(kb_entry_id="KB-1", category="ISSUE", intent="Clock-in location error", score=0.9,
                        instruction="I can't clock in, location not available", response=CLOCK_IN)
    return AnswerInput(ticket_text=f"Customer: {customer_text}", kb_candidates=[entry], customer_text=customer_text)


def test_the_customer_suggesting_it_never_backs_an_instruction(caplog):
    data = _input("still the same error. should I disable the firewall?")
    reply = chat_response._frame("Allow location for the app in your phone settings and try again. "
                                 "You can also disable the firewall.", data, "answer")
    assert "firewall" not in reply.text and reply.text.startswith("Allow location")
    assert "an instruction the KB entry doesn't give" in caplog.text


def test_a_procedure_with_a_step_dropped_is_regenerated_then_the_entrys_own(monkeypatch):
    replies = iter(["1. Restart your phone.\n2. Allow location for the app in your phone settings.",
                    "1. Reinstall the app.\n2. Allow location for the app in your phone settings."])
    monkeypatch.setattr(provider, "complete_text", lambda *a, **k: next(replies))
    text = chat_response.answer(_input("I can't clock in")).text
    assert "Restart" not in text and "Reinstall" not in text
    assert text.startswith("Clock-in needs location access")             # the entry's own answer
