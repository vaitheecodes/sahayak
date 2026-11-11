"""Steps must come from the knowledge base.

A step the model writes (a numbered or bulleted line in a chat answer, a
technician's suggested next step) is kept only when the KB text it was
given supports it:
- every menu path in it ("Settings > Leave > Policies") appears in the KB
  text;
- every hostname, port or number in it appears in the KB text (no
  invented "app.example.com on 443" or "500 a day");
- most of its content words (STEP_SUPPORT) appear in the KB text.

Deterministic and conservative: a step the KB doesn't back is dropped,
never rewritten.
"""

from __future__ import annotations

import re

from backend.ai_service.schemas import KBCandidate

STEP_SUPPORT = 0.6
_WORD = re.compile(r"[a-z0-9]+")
_STEP_LINE = re.compile(r"^(\s*)(\d+[.)]|[-*•])(\s+)(.*)$")
_MENU_PATH = re.compile(r"[A-Za-z][\w&'/ ]*?(?:\s*(?:>|→)\s*[A-Za-z][\w&'/ ]*)+")
_HOSTNAME = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.(?:com|net|org|io|in|eu|au|cn|jp|ca|uk)\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
_COMMON = frozenset("""
    a an the and or but if then than to of in on at by for with from into onto as is are be been
    it its this that these those you your yours we our they their them there here can could
    should would will may might must do does did done make sure check go open click select choose
    use using want need please also any all each every some more most other such only just
    step steps first next then finally again sure
""".split())


def kb_text(candidates: list[KBCandidate]) -> str:
    return "\n".join(f"{c.instruction}\n{c.response}" for c in candidates)


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def content_words(text: str) -> set[str]:
    """Stemmed words of `text` that carry meaning (no filler, no short words)."""
    return {_stem(w) for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _COMMON}



def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _path_in(path: str, kb_norm: str) -> bool:
    """The menu path appears in the KB text. The first and last parts may
    carry surrounding words ("Go to Settings", "Policies and click Add"), so any
    tail of the first part and any head of the last part will do."""
    parts = [p.strip().lower() for p in re.split(r"\s*(?:>|→)\s*", path) if p.strip()]
    first, last, middle = parts[0].split(), parts[-1].split(), parts[1:-1]
    for i in range(len(first)):
        for j in range(len(last), 0, -1):
            seq = [" ".join(first[i:]), *middle, " ".join(last[:j])]
            if re.search(r"\s*(?:>|→)\s*".join(re.escape(p) for p in seq), kb_norm):
                return True
    return False


def supported(step: str, kb: str) -> bool:
    """True when the KB text `kb` backs `step` (see the module docstring)."""
    if not kb.strip():
        return False
    kb_norm = _normal(kb)
    if any(not _path_in(path, kb_norm) for path in _MENU_PATH.findall(step)):
        return False
    for host in _HOSTNAME.findall(step):
        if host.lower() not in kb_norm:
            return False
    kb_numbers = set(_NUMBER.findall(kb))
    if any(n not in kb_numbers for n in _NUMBER.findall(step)):
        return False
    words = content_words(step)
    if not words:
        return True
    return len(words & content_words(kb)) / len(words) >= STEP_SUPPORT


def ground_steps(text: str, kb: str) -> tuple[str, int]:
    """`text` without its step lines (numbered or bulleted) that the KB
    doesn't support; numbered steps are renumbered. Returns the text and
    how many steps were dropped."""
    out, dropped, number = [], 0, 0
    for line in text.splitlines():
        match = _STEP_LINE.match(line)
        if not match:
            out.append(line)
            continue
        indent, marker, space, body = match.groups()
        if not supported(body, kb):
            dropped += 1
            continue
        if marker[0].isdigit():
            number += 1
            marker = f"{number}{marker[-1]}"
        out.append(f"{indent}{marker}{space}{body}")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip(), dropped


# ---------------------------------------------------------------------------
# Specific values in any sentence of a reply
# ---------------------------------------------------------------------------
# Only values a customer would copy: domains and URLs, policy directives
# with their sources, quoted or `backticked` text, paths, and numbers that
# read as a version, a port or a limit. "Wait about 2 minutes", "step 1"
# and product names are not values.
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s'\"`<>)]+", re.IGNORECASE)
_DOMAIN = re.compile(r"\b(?:[a-z0-9-]{2,}\.)+(?:com|net|org|io|in|eu|au|cn|jp|ca|uk|us|de|co|dev|app|ai|cloud)\b",
                     re.IGNORECASE)
_SOURCE = r"(?:'[^'\s]+'|[a-z][a-z0-9+.-]*:(?://)?[^\s;'\"]*|\*|(?:[a-z0-9*-]+\.)+[a-z]{2,})"
_DIRECTIVE = re.compile(rf"\b([a-z]+(?:-[a-z]+)*-src)\b((?:\s+{_SOURCE})*)", re.IGNORECASE)
_QUOTED = re.compile(r"`([^`\n]{2,200})`|\"([^\"\n]{2,200})\"|“([^”\n]{2,200})”|(?<!\w)'([^'\n]{2,120})'(?!\w)")
_PATH = re.compile(r"(?<![\w.:/])/(?:[\w.-]+/)+[\w.-]*|\b[A-Za-z]:\\[^\s'\"]+")
_VERSION = re.compile(r"(?<![\w.])v?\d+(?:\.\d+){1,3}(?![\w.])")
_PORT = re.compile(r"\bport\s+(\d{2,5})\b|(?<=[a-z0-9]):(\d{2,5})\b", re.IGNORECASE)
_LIMIT = re.compile(r"(?<![\w.])\d[\d,.]*\s*(?:kb|mb|gb|tb|ms|requests?|calls?|characters|chars|users|records)\b"
                    r"|(?<![\w.])\d[\d,.]*\s+(?:a|per)\s+(?:second|minute|hour|day|week|month)\b"
                    r"|(?<![\w.])\d[\d,.]*\s*/\s*(?:s|sec|min|hour|day)\b", re.IGNORECASE)


def _directives(text: str) -> dict[str, list[frozenset]]:
    found: dict[str, list[frozenset]] = {}
    for name, sources in _DIRECTIVE.findall(text):
        found.setdefault(name.lower(), []).append(frozenset(s.lower() for s in sources.split()))
    return found


def value_problem(sentence: str, allowed: str) -> str | None:
    """The first specific value in `sentence` that `allowed` (the KB text
    plus the customer's own messages) doesn't contain, else None. A
    directive with sources must match one in `allowed` source for source:
    "script-src 'self'" is not "script-src 'self' https://cdn.example.com"."""
    norm = _normal(allowed)
    known = _directives(allowed)
    for name, sources in _directives(sentence).items():
        for source_set in sources:
            if source_set and source_set not in known.get(name, []):
                return f"{name} {' '.join(sorted(source_set))}"
            if not source_set and name not in norm:
                return name
    rest = _DIRECTIVE.sub(" ", sentence)
    values = [u.rstrip(".,;:") for u in _URL.findall(rest)]
    rest = _URL.sub(" ", rest)
    values += _DOMAIN.findall(rest)
    values += [next(g for g in groups if g) for groups in _QUOTED.findall(rest)]
    values += _PATH.findall(rest) + _VERSION.findall(rest)
    values += [a or b for a, b in _PORT.findall(rest)] + _LIMIT.findall(rest)
    return next((v for v in values if _normal(v) not in norm), None)


def ground_values(text: str, allowed: str) -> tuple[str, int]:
    """`text` without the sentences (and step lines) carrying a specific
    value `allowed` doesn't contain (value_problem). Returns the text and
    how many sentences were dropped."""
    out, dropped = [], 0
    for line in text.splitlines():
        if _STEP_LINE.match(line):
            if value_problem(line, allowed):
                dropped += 1
                continue
            out.append(line)
            continue
        kept = []
        for sentence in _SENTENCE_END.split(line.strip()):
            if sentence and value_problem(sentence, allowed):
                dropped += 1
            else:
                kept.append(sentence)
        out.append(" ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip(), dropped


# A sentence that promises steps or a list. One that only ends in a colon
# may introduce a quote or a code block, so it counts only at the very end.
_LEAD_IN_PHRASE = re.compile(
    r"\b(here'?s how|here is how|follow (these|the) steps|as follows|do the following)\W*$", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def strip_dangling_lead_ins(text: str, followed: bool = False) -> str:
    """`text` without lead-in sentences ("Here's how:", "follow these
    steps:") that no step or list line follows, as left when every
    step was dropped or the model wrote none. Earlier sentences of the
    same line stay. `followed`: code adds a block after the text (a KB
    entry's snippets), which a final colon may introduce."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        following = next((rest for rest in lines[i + 1:] if rest.strip()), "```" if followed else "")
        if not line.strip() or _STEP_LINE.match(line) or _STEP_LINE.match(following):
            continue
        sentences = _SENTENCE_END.split(line.strip())
        while sentences and (_LEAD_IN_PHRASE.search(sentences[-1])
                             or (not following and sentences[-1].rstrip().endswith(":"))):
            sentences.pop()
        lines[i] = " ".join(sentences)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def grounded_steps(steps: list[str], kb: str) -> list[str]:
    """The suggested steps the KB text supports."""
    return [s for s in steps if supported(s, kb)]
