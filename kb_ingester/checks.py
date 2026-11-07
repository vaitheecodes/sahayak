"""Checks the drafter's output must pass, done by code, never the model.

- quote_offset: a step's quote must be a passage of its chunk (compared
  after normalising case, whitespace, spacing around punctuation, doubled
  backslashes, quote marks and dashes), 15-500 characters.
- answer_problem: the answer must be a paraphrase. It is refused if it
  shares a run of VERBATIM_RUN_WORDS words with the chunk, or if more
  than MAX_TRIGRAM_OVERLAP of its word trigrams appear in the chunk.
  Only the answer: steps are meant to stay close to their quotes.
- injection_signals: phrasing that tries to instruct a model ("ignore
  previous instructions", role markers, "you are now ..."). A chunk with
  any is flagged for the reviewer; drafted text with any, or with a link
  the chunk doesn't contain, is flagged too. Flagged drafts are never
  treated differently by the model call itself: it has no tools and
  every draft waits for a person anyway.
"""

from __future__ import annotations

import re
import unicodedata

MIN_QUOTE_CHARS = 15
MAX_QUOTE_CHARS = 500
VERBATIM_RUN_WORDS = 12
MAX_TRIGRAM_OVERLAP = 0.6

_TRANSLATE = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ", "…": "...",
})
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(_TRANSLATE).lower()
    # Markdown emphasis and list markers aren't part of what a quote says.
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"(?m)^\s*(?:[-+]|\d+\.)\s+", "", text)
    # Models double backslashes when they escape a quote for JSON, and
    # drop or add the space before punctuation ("characters ., -").
    text = text.replace("\\\\", "\\")
    text = " ".join(text.split())
    text = re.sub(r" ([,.;:!?)\]])", r"\1", text)
    return re.sub(r"([(\[]) ", r"\1", text)


def quote_problem(quote: str, chunk_text: str) -> str | None:
    """None when the quote is a passage of the chunk; else a reason code."""
    norm = normalize(quote).strip(" .\"'")
    if not norm:
        return "quote_missing"
    if not MIN_QUOTE_CHARS <= len(norm) <= MAX_QUOTE_CHARS:
        return "quote_length"
    if norm not in normalize(chunk_text):
        return "quote_not_in_source"
    return None


def quote_offset(quote: str, chunk_text: str) -> int | None:
    """Where the quote starts in the normalised chunk, or None."""
    if quote_problem(quote, chunk_text):
        return None
    return normalize(chunk_text).find(normalize(quote).strip(" .\"'"))


def _words(text: str) -> list[str]:
    return _WORD.findall(normalize(text))


def _ngrams(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def answer_problem(answer: str, chunk_text: str) -> str | None:
    """None for a paraphrase; "answer_verbatim" or "answer_too_close"."""
    words, source = _words(answer), _words(chunk_text)
    if len(words) >= VERBATIM_RUN_WORDS and _ngrams(words, VERBATIM_RUN_WORDS) & _ngrams(
            source, VERBATIM_RUN_WORDS):
        return "answer_verbatim"
    trigrams = _ngrams(words, 3)
    if len(words) >= 8 and trigrams:
        shared = len(trigrams & _ngrams(source, 3)) / len(trigrams)
        if shared > MAX_TRIGRAM_OVERLAP:
            return "answer_too_close"
    return None


_INJECTION = [
    ("ignore_instructions", re.compile(
        r"\b(ignore|disregard|forget|override)\s+(all\s+|any\s+)?(of\s+)?(the\s+|your\s+|my\s+)?"
        r"(previous|prior|above|earlier|preceding|system|original)\s+"
        r"(instructions?|prompts?|rules|directions|messages|guidelines)\b", re.IGNORECASE)),
    ("role_change", re.compile(
        r"\b(you are now|from now on,? you (are|will|must)|act as (an?|the) (ai|assistant|model|system)|"
        r"pretend (to be|you are) (an?|the)|new system (instructions?|prompt)|developer mode|jailbreak)\b",
        re.IGNORECASE)),
    ("prompt_probe", re.compile(
        r"\b(system prompt|reveal (your|the) (prompt|instructions)|print (your|the) (prompt|instructions))\b",
        re.IGNORECASE)),
    ("role_marker", re.compile(
        r"<\|?\s*(im_start|im_end|system|assistant|user)\s*\|?>|^\s*(system|assistant)\s*:|\[/?INST\]",
        re.IGNORECASE | re.MULTILINE)),
    ("data_block_tag", re.compile(r"</?\s*(source_chunk|steps_to_check|known_terms|categories)\b",
                                  re.IGNORECASE)),
    ("review_steering", re.compile(
        r"\b(auto[- ]?approve|approve (this|all|these) (entry|entries|drafts?)|mark (this|it) as approved)\b",
        re.IGNORECASE)),
]
_LINK = re.compile(r"https?://[^\s)>\]\"']+|\bwww\.[^\s)>\]\"']+", re.IGNORECASE)


def injection_signals(text: str) -> list[str]:
    return [name for name, pattern in _INJECTION if pattern.search(text or "")]


def output_signals(fields: list[str], chunk_text: str) -> list[str]:
    """Signals in drafted text: injection phrasing, or a link the chunk
    doesn't contain."""
    joined = "\n".join(f for f in fields if f)
    signals = injection_signals(joined)
    source = normalize(chunk_text)
    if any(normalize(link).rstrip(".,;") not in source for link in _LINK.findall(joined)):
        signals.append("unknown_link")
    return signals
