"""Checks the drafter's output must pass, done by code, never the model.

- quote_offset: a step's quote must be a passage of its chunk (compared
  after normalising case, whitespace, spacing around punctuation, doubled
  backslashes, quote marks and dashes), 15-500 characters.
- answer_problem: the answer must be a paraphrase. It is refused if it
  shares a run of VERBATIM_RUN_WORDS words with the chunk, or if more
  than MAX_TRIGRAM_OVERLAP of its word trigrams appear in the chunk.
  Only the answer: steps are meant to stay close to their quotes.
- snippet_problem: a snippet (code, config or a command, shown to the
  customer as it is) must be copied verbatim from the chunk (whitespace
  aside), at most MAX_SNIPPET_CHARS, and code: inside a ``` block or a
  `backticked` span of the chunk, or lines that read as code.
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
MAX_SNIPPET_CHARS = 600

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


_FENCED = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
_BACKTICKED = re.compile(r"`([^`\n]+)`")
_CODE_LINE = re.compile(
    r"[<>{}=$|\\]|^\s*(?:sudo|pip3?|npm|npx|yarn|python3?|node|curl|wget|git|docker|kubectl|brew|"
    r"apt(?:-get)?|choco|winget|powershell|cd|ls|cp|mv|mkdir|export|set)\b")


def _spaced(text: str) -> str:
    return " ".join(text.split())


def snippet_problem(snippet: str, chunk_text: str) -> str | None:
    """None for a code/config/command snippet copied from the chunk; else
    a reason code (snippet_length, snippet_not_in_source, snippet_prose)."""
    text = _spaced(snippet)
    if not text or len(snippet.strip()) > MAX_SNIPPET_CHARS:
        return "snippet_length"
    if text not in _spaced(chunk_text):
        return "snippet_not_in_source"
    code = [_spaced(b) for b in _FENCED.findall(chunk_text)] + _BACKTICKED.findall(chunk_text)
    lines = [line for line in snippet.splitlines() if line.strip()]
    if any(text in block for block in code) or all(_CODE_LINE.search(line) for line in lines):
        return None
    return "snippet_prose"


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


def lead_in_problem(quote: str, chunk_text: str) -> str | None:
    """A quote ending with a colon ("On Windows, run:") only introduces the
    instruction; the command, value or list after it is the instruction.
    "quote_lead_in" when the section continues after such a quote."""
    if not quote.rstrip().endswith(":"):
        return None
    norm = normalize(quote).strip(" .\"'")
    source = normalize(chunk_text)
    at = source.find(norm)
    if at < 0:
        return None  # quote_problem reports it
    return "quote_lead_in" if source[at + len(norm):].strip() else None


# Words too generic to be a product term on their own.
GENERIC_WORDS = frozenset("""
    account accounts admin app application apps attachment button buttons calendar dashboard data date dates
    description details document documents email feature features field fields file files form forms help
    home link links list menu name option options page pages password profile query report reports request
    requests search setting settings status tab table type url user users value values view window
""".split())
_FILE_OR_PATH = re.compile(r"[/\\]|^\.|\.[A-Za-z0-9]{1,5}$|^[\w-]+\.[\w-]+$")
_URL_BITS = re.compile(r"://|^www\.|[?=&#%]|\burl\b|\bquery\b|\bendpoint\b|\bparam", re.IGNORECASE)


def term_label_problem(label: str, chunk_text: str) -> str | None:
    """Why a proposed term isn't a product term (None: it may be one):
    term_field_label (the label of a "Field: ..." line), term_file (a file
    name or path), term_url (a URL or a part of one), term_generic (a single
    generic or lower-case word, e.g. "dates", "tutorial-env")."""
    label = label.strip()
    if re.search(rf"(?im)^\s*(?:[-*+]\s+|\d+\.\s+)?{re.escape(label)}\s*(?:\([^)]*\))?\s*:", chunk_text):
        return "term_field_label"
    if _URL_BITS.search(label):
        return "term_url"
    if _FILE_OR_PATH.search(label):
        return "term_file"
    words = label.split()
    if len(words) == 1 and (label.lower() in GENERIC_WORDS or label == label.lower()):
        return "term_generic"
    return None
