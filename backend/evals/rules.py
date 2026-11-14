"""The contract's code rules (docs/CHAT_CONTRACT.md). check() returns
{rule number: (verdict, detail)}, verdict "pass" / "fail" / "n/a"."""

from __future__ import annotations

import re

from backend import request_kind
from backend.ai_service import chat_response, grounding

_FENCE = re.compile(r"```.*?```", re.DOTALL)
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
_STEP = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
SMALL_TALK = re.compile(r"\W*(hi+|hello+|hey+|hai|good (morning|afternoon|evening)|vanakkam|namaste)\W*",
                        re.IGNORECASE)
_GREETING = re.compile(r"\W*(hi|hello|hey|welcome|good (morning|afternoon|evening)|vanakkam|namaste)\b",
                       re.IGNORECASE)
BARE_ACK = re.compile(r"\W*(ok(ay)?|k|thanks?|thank you|thx|hmm+|hm+|ok thanks)\W*", re.IGNORECASE)
NO_GUIDE = "don't have a guide"
_TICKET_RAISED = re.compile(r"\b(raised|passed|created)\b.{0,40}\bticket\b", re.IGNORECASE)
_TROUBLESHOOTING = re.compile(r"what have you (already )?tried|which screen|what do you see|error message"
                              r"|at which (screen|step)", re.IGNORECASE)
_GENERIC = [t.split("{")[0] for t in (chat_response.STEP_QUESTION, chat_response.DETAIL_QUESTION,
                                      chat_response.TRIED_QUESTION, chat_response.GENERIC_SUBJECT_QUESTION)]
_GENERIC_RE = re.compile(r"(provide|share|give)( me)? (more|some|additional) (details|information|context)"
                         r"|tell me more about (the|your) (issue|problem)", re.IGNORECASE)
_INTERNAL = re.compile(r"\bKB-\d{3,}\b|NOT_COVERED|\[(Customer|Your) [A-Z]?[a-z]+\]|</?(transcript|kb_[a-z_]+)>"
                       r"|\bkb_entry\b|\bgrounding\b")
_DOMAIN = re.compile(r"\b((?:[a-z0-9-]+\.)+)([a-z]{2,6})\b", re.IGNORECASE)
COVERED_KINDS = {"paraphrased", "vague", "typo_mixed", "direct", "pasted_error", "small_talk", "topic_switch",
                 "angry", "ok_thanks", "followup", "negation"}


def _prose(text: str) -> str:
    return _FENCE.sub(" ", text)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCES.split(_prose(text)) if s.strip()]


def _overlap(a: set, b: set) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def is_question(reply: str) -> bool:
    """A clarifying reply: ends on a question, no steps, no snippet."""
    sentences = _sentences(reply)
    # Short: an answer that ends on a check-in ("Can you confirm...?") is an answer.
    return (bool(sentences) and sentences[-1].endswith("?") and len(sentences) <= 2
            and not _STEP.search(reply) and "```" not in reply)


def is_answer(reply: str) -> bool:
    return bool(_STEP.search(reply) or "```" in reply) or (
        len(_sentences(reply)) >= 2 and not is_question(reply) and NO_GUIDE not in reply)


def _generic(reply: str) -> bool:
    """A template question, or "which part of the product?" without the options."""
    bare_subject = re.search(r"\bwhich part of\b", reply, re.IGNORECASE) and ":" not in reply and " or " not in reply
    return bool(bare_subject or _GENERIC_RE.search(reply)) or any(
        g.strip() and g.strip() in reply for g in _GENERIC if not g.startswith("Which part of"))


def kb_text(pack: dict) -> str:
    def walk(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from walk(v)
        elif isinstance(value, list):
            for v in value:
                yield from walk(v)
    return "\n".join(walk(pack["entries"]))


def _contradicting_snippet(reply: str) -> str | None:
    """A domain the prose names whose snippet only has the same name under
    another ending (.com in the policy, .eu in the text)."""
    fenced = " ".join(_FENCE.findall(reply))
    if not fenced:
        return None
    in_fence = {(m.group(1).lower(), m.group(2).lower()) for m in _DOMAIN.finditer(fenced)}
    prose = _prose(reply)
    for m in _DOMAIN.finditer(prose):
        stem, end = m.group(1).lower(), m.group(2).lower()
        ends = {e for s, e in in_fence if s == stem}
        # A line naming both ("the example uses X; use Y in its place") resolves it.
        explained = any(f"{stem}{end}" in line.lower() and any(f"{stem}{e}" in line.lower() for e in ends)
                        for line in prose.splitlines())
        explained = explained or chat_response.REGION_NOTE in prose   # the fixed neutral line
        if ends and end not in ends and not explained:
            return f"text says {stem}{end}, snippet has {stem}{'/'.join(sorted(ends))}"
    return None


def check(result: dict, pack: dict, kb: str) -> dict[int, tuple[str, str]]:
    case, turns = result["case"], result["turns"]
    kind, expected = case["kind"], case["expected"]
    out: dict[int, tuple[str, str]] = {}
    replies = [t["bot"] for t in turns]
    customer = " ".join(t["customer"] for t in turns)
    entry = next((e for e in pack["entries"] if e["kb_entry_id"] == case.get("entry_id")), None)

    def verdict(rule, problem, applies=True):
        out[rule] = ("n/a", "") if not applies else (("fail", problem) if problem else ("pass", ""))

    # 1. Values in the replies are in the KB or the customer's messages.
    allowed = kb_text(pack) + "\n" + customer
    invented = next((f"{v!r} in {s!r}" for r in replies for s in _sentences(r)
                     if (v := grounding.value_problem(s, allowed))), None)
    verdict(1, invented)

    # 2. Small talk: a short greeting, no hand-off, never the problem text.
    greeted = [n for n, t in enumerate(turns) if SMALL_TALK.fullmatch(t["customer"])]
    problem = None
    for n in greeted:
        t = turns[n]
        if t["status"] != "active" or NO_GUIDE in t["bot"] or len(t["bot"].split()) > 40:
            problem = f"turn {n + 1}: {t['status']}, {len(t['bot'].split())} words"
        elif not _GREETING.match(t["bot"]):
            problem = f"turn {n + 1}: no greeting: {t['bot'][:80]!r}"
    if greeted and len(turns) > 1 and result.get("issue") and SMALL_TALK.fullmatch(result["issue"]):
        problem = problem or f"the chat's problem text is {result['issue']!r}"
    verdict(2, problem, bool(greeted))

    # 3. A covered question is answered, never escalated or "no guide".
    covered = kind in COVERED_KINDS and expected == "answer"
    problem = None
    if covered:
        # Before the first answer: a hand-off after an answer the customer
        # says didn't work is right.
        first = next((n for n, r in enumerate(replies) if is_answer(r)), len(replies))
        if any(NO_GUIDE in r for r in replies[:first + 1]):
            problem = "said it has no guide"
        elif any(t["status"] == "escalated" for t in turns[:first]) or (
                first < len(turns) and turns[first]["status"] == "escalated" and not is_answer(replies[first])):
            problem = "escalated"
        elif first == len(replies):
            problem = "never answered"
    verdict(3, problem, covered)

    # 4. How-to: no troubleshooting questions.
    how_to = entry is not None and entry.get("kind") == "how-to" and kind != "pasted_error"
    bad = next((r for r in replies if is_question(r) and _TROUBLESHOOTING.search(r)), None)
    verdict(4, bad and f"asked: {bad[:160]!r}", how_to)

    # 5. At most one clarifying question (one per topic), never generic.
    questions = [r for n, r in enumerate(replies) if is_question(r) and n not in greeted]
    limit = 2 if kind == "topic_switch" else 1
    generic = next((q for q in questions if _generic(q)), None)
    verdict(5, (f"{len(questions)} clarifying questions" if len(questions) > limit else None)
            or (generic and f"generic: {generic[:160]!r}"))

    # 6. Never the same question twice.
    asked = [(s, grounding.content_words(s)) for r in replies for s in _sentences(r) if s.endswith("?")]
    repeat = next((b for i, (a, wa) in enumerate(asked) for b, wb in asked[i + 1:]
                   if a == b or (min(len(wa), len(wb)) >= 3 and _overlap(wa, wb) >= 0.7)), None)
    verdict(6, repeat and f"asked again: {repeat!r}")

    # 7. "ok" / "thanks" / "hmm" never close the chat.
    closed = next((t["customer"] for t in turns if BARE_ACK.fullmatch(t["customer"]) and t["status"] == "resolved"),
                  None)
    verdict(7, closed and f"closed on {closed!r}", any(BARE_ACK.fullmatch(t["customer"]) for t in turns))

    # 8. No repeated sentences in a reply.
    problem = None
    for r in replies:
        units = [(s, grounding.content_words(s)) for s in _sentences(r)]
        for i, (a, wa) in enumerate(units):
            for b, wb in units[i + 1:]:
                if a == b or (min(len(wa), len(wb)) >= 5 and _overlap(wa, wb) >= 0.8):
                    problem = problem or f"{a!r} / {b!r}"
    # ... nor across one turn's messages: the ticket announced twice ("no guide, I've raised a ticket" + the notice).
    twice = next((t for t in turns if sum(bool(_TICKET_RAISED.search(m)) for m in t.get("bot_messages", [])) > 1),
                 None)
    verdict(8, problem or (twice and f"ticket announced twice after {twice['customer'][:80]!r}"))

    # 9. Not covered: "no guide" and a ticket within two replies.
    first_two = turns[:2]
    # The contract: "I don't have a guide" and a ticket, or the offer of one (chat_response.FOLLOWUP_NOT_COVERED).
    handled = any(NO_GUIDE in t["bot"] or "guide I have doesn't cover" in t["bot"] or t["status"] == "escalated"
                  or t["ticket_id"] for t in first_two)
    verdict(9, None if handled else "no 'no guide' / ticket within two replies", expected == "not_covered")

    # 10. The snippet never contradicts the text.
    verdict(10, next((p for r in replies if (p := _contradicting_snippet(r))), None))

    # 11. Follow-ups after an answer get steps, snippet or sources.
    problem, applies = None, False
    for prev, t in zip(turns, turns[1:]):
        if is_answer(prev["bot"]) and (request_kind.asks_for_steps(t["customer"])
                                       or request_kind.asks_for_sources(t["customer"])):
            applies = True
            if t["status"] == "escalated" or NO_GUIDE in t["bot"] or _generic(t["bot"]) or not t["bot"].strip():
                problem = problem or f"{t['customer']!r} got {t['bot'][:160]!r}"
    verdict(11, problem, applies)

    # 12. Off-topic: brief.
    long_reply = next((r for r in replies if len(_prose(r).split()) > 80), None)
    verdict(12, long_reply and f"{len(_prose(long_reply).split())} words", kind == "out_of_scope")

    # 13. A request for a human escalates at once.
    asked_human = [n for n, t in enumerate(turns) if re.search(r"\b(human|person|agent|someone)\b", t["customer"], re.I)
                   and re.search(r"\b(talk|speak|connect|want)\b", t["customer"], re.I)]
    verdict(13, None if not asked_human or turns[asked_human[0]]["status"] == "escalated"
            else "not escalated", bool(asked_human))

    # 14. Always an answer.
    broken = next((t for t in turns if t["ai_error"] or not t["bot"].strip()), None)
    verdict(14, (broken and f"{broken['ai_error'] or 'empty reply'}") or result.get("error"))

    # 15. No internal text.
    leak = next((m.group(0) for r in replies if (m := _INTERNAL.search(r))), None)
    verdict(15, leak and f"shows {leak!r}")
    return out
