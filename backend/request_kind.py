"""What kind of request a message (or a KB entry's question) is.

- how-to: the customer wants to add, set up or configure something
  ("I need to add a new user, how to do?"). Never a fault: nothing is
  broken, so there is no error to ask about and no troubleshooting entry
  can answer it.
- fault: something is broken or missing ("the page shows an error",
  "unable to log in", "emails not received").
- error_reported: the customer mentioned an error (text, code, failure).
  Only then may a reply ask for the exact error message.

Plain regular expressions: cheap, deterministic, and easy to test. Used by
graph.py (routing, grounding) and kb_retrieval.py (how-to searches skip
troubleshooting entries).
"""

from __future__ import annotations

import re

_FAULT = re.compile(
    r"\b(errors?|fail\w*|down|outage|broken|stopped|missing|wrong|false|issues?|problems?"
    r"|unable|cannot|can'?t|couldn'?t|won'?t|isn'?t|aren'?t|doesn'?t|don'?t|didn'?t|not"
    r"|suspended|crash\w*|timeouts?|timed out|denied|invalid|rejected|troubleshoot\w*"
    r"|no (data|alerts?|metrics|emails?))\b",
    re.IGNORECASE)
_ERROR = re.compile(
    r"\b(errors?|fail\w*|exceptions?|denied|invalid|rejected|timed out|timeouts?|error code"
    r"|status code|http \d{3}|\d{3} (error|response))\b",
    re.IGNORECASE)
_TASK = re.compile(
    r"\b(add|adding|set ?up|set (?:it|this|that|them) up|setting up|configure|configuring|create|creating|install|installing"
    r"|enable|enabling|integrate|integrating|connect|connecting|track|tracking"
    r"|change|changing|update|updating|edit|modify|generate|schedule|apply|submit|request"
    r"|download|export|import|upload|assign|approve|register|invite)\b",
    re.IGNORECASE)
# Task verbs as single words (graph.shares_customer_words compares the
# objects of a request, not its verb).
TASK_WORDS = frozenset("""
    add adding set setup setting configure configuring create creating install installing enable
    enabling integrate integrating connect connecting track tracking change changing update
    updating edit modify generate schedule apply submit request download export import upload
    assign approve register invite
""".split())
_HOW = re.compile(
    r"\b(how|steps?|guide|way to|want to|wants to|need to|needs to|would like to|like to|trying to"
    r"|wanna|planning to|is it possible to|can i|can we|could i)\b",
    re.IGNORECASE)
_UNSURE = re.compile(r"\b(not sure|unsure|no idea|don'?t know|dunno|idk|not certain)\b", re.IGNORECASE)
_STARTS_WITH_TASK = re.compile(r"^\s*(please\s+)?(add|set ?up|configure|create|install|enable|integrate|connect"
                               r"|apply|submit|export|download|import|upload|invite)\b",
                               re.IGNORECASE)


# The whole message asks for the steps again: "ok how to solve it",
# "what next", "steps please". Anything longer is a real question.
_STEPS_REQUEST = re.compile(
    r"(?:(?:ok|okay|so|then|and|alright|right|fine)\s+)*"
    r"(?:(?:please\s+)?(?:give|show|send|tell)\s+me\s+(?:the\s+)?steps|(?:the\s+|next\s+)?steps"
    r"|what\s+(?:are\s+)?the\s+steps|what\s+(?:next|now)|what\s+(?:do|should)\s+i\s+do(?:\s+(?:next|now))?"
    r"|how\s+(?:do\s+i|can\s+i|should\s+i|to|do\s+we)\s+(?:solve|fix|resolve|do)\s+(?:it|this|that))"
    r"(?:\s+(?:please|pls|then|now))*")


# Small talk only: a greeting gets a greeting back, never a KB lookup or a
# problem text (docs/CHAT_CONTRACT.md rule 2).
_SMALL_TALK = re.compile(r"(?:(?:hi+|hello+|hey+|hai|hii+|good (?:morning|afternoon|evening)|vanakkam|namaste"
                         r"|namaskar|greetings|yo)\s*)+(?:there|team|all|everyone|sir|madam)?")


def is_small_talk(text: str) -> bool:
    return bool(_SMALL_TALK.fullmatch(" ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())))


# "what are the sources?" after an answer: the guide and its page, by code.
_SOURCES_REQUEST = re.compile(
    r"(?:(?:ok|okay|so|and|also|then)\s+)*(?:(?:what|which|where)\s+(?:are|is|s)\s+(?:the|your|its|this)\s+"
    r"sources?|whats\s+the\s+sources?|(?:the\s+)?sources?(?:\s+(?:page|link|url|please|pls))?|(?:where|what)\s+(?:is|does|did)\s+"
    r"(?:this|that|it)\s+come\s+from|(?:give|show|send)\s+me\s+the\s+sources?(?:\s+(?:page|link))?)"
    r"(?:\s+(?:please|pls))?")


_YES = re.compile(r"(?:yes|yeah|yep|yup|yea|correct|exactly|that'?s (?:right|it|correct))\b", re.IGNORECASE)
_NO = re.compile(r"\b(?:no|not|nope|never)\b|n't", re.IGNORECASE)


def is_affirmative(text: str) -> bool:
    """A short "yes" to a question just asked ("Yes, the mobile app"); never one that also says no."""
    text = (text or "").strip()
    return bool(_YES.match(text)) and not _NO.search(text) and len(text.split()) <= 8


def asks_for_sources(text: str) -> bool:
    return bool(_SOURCES_REQUEST.fullmatch(" ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())))


def asks_for_steps(text: str) -> bool:
    return bool(_STEPS_REQUEST.fullmatch(" ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())))


def is_fault(text: str) -> bool:
    return bool(_FAULT.search(text or ""))


def error_reported(text: str) -> bool:
    return bool(_ERROR.search(text or ""))


def is_unsure(text: str) -> bool:
    """"Not sure", "no idea": an answer that gives nothing, not a fault."""
    return bool(_UNSURE.search(text or ""))


def mentions_task(text: str) -> bool:
    """Names something to add, set up, configure or change (a KB entry
    that can answer a how-to does)."""
    return bool(_TASK.search(text or ""))


def is_how_to(text: str) -> bool:
    """A request to add, set up or configure something, with no sign of a
    fault."""
    text = text or ""
    if is_fault(text) or not _TASK.search(text):
        return False
    return bool(_HOW.search(text) or _STARTS_WITH_TASK.search(text))
