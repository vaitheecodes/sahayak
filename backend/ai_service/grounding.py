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
    return "\n".join(f"{c.instruction}\n{c.response}\n{c.source_url or ''}" for c in candidates)


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


def value_problem(sentence: str, allowed: str, hosts_allowed: str | None = None) -> str | None:
    """The first specific value in `sentence` that `allowed` (the KB text
    plus the customer's own messages) doesn't contain, else None. A
    directive with sources must match one in `allowed` source for source:
    "script-src 'self'" is not "script-src 'self' https://cdn.example.com".
    URLs and domains (host and path) are checked against `hosts_allowed`
    when given: the answering entry and the customer, never another entry."""
    norm = _normal(allowed)
    host_norm = _normal(hosts_allowed) if hosts_allowed is not None else norm
    known = _directives(allowed)
    for name, sources in _directives(sentence).items():
        for source_set in sources:
            if source_set and source_set not in known.get(name, []):
                return f"{name} {' '.join(sorted(source_set))}"
            if not source_set and name not in norm:
                return name
    rest = _DIRECTIVE.sub(" ", sentence)
    hosts = [u.rstrip(".,;:/") for u in _URL.findall(rest)]
    rest = _URL.sub(" ", rest)
    hosts += _DOMAIN.findall(rest)
    if bad := next((v for v in hosts if _normal(v) not in host_norm), None):
        return bad
    values = []
    values += [next(g for g in groups if g) for groups in _QUOTED.findall(rest)]
    values += _PATH.findall(rest) + _VERSION.findall(rest)
    values += [a or b for a, b in _PORT.findall(rest)] + _LIMIT.findall(rest)
    return next((v for v in values if _normal(v) not in norm), None)


def ground_values(text: str, allowed: str, hosts_allowed: str | None = None) -> tuple[str, list[tuple[str, str]]]:
    """`text` without the sentences (and step lines) carrying a specific
    value `allowed` doesn't contain (value_problem). Returns the text and
    each dropped sentence with the value that dropped it."""
    out, dropped = [], []
    for line in text.splitlines():
        if _STEP_LINE.match(line):
            problem = value_problem(line, allowed, hosts_allowed)
            if problem:
                dropped.append((line.strip(), problem))
                continue
            out.append(line)
            continue
        kept = []
        for sentence in _SENTENCE_END.split(line.strip()):
            problem = value_problem(sentence, allowed, hosts_allowed) if sentence else None
            if problem:
                dropped.append((sentence, problem))
            else:
                kept.append(sentence)
        out.append(" ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip(), dropped


# A sentence or step that says again what an earlier sentence of the reply
# said ("allow the servers in your policy" / "1. Update your policy to allow
# the servers"): most of its content words (RESTATES) are in one earlier
# sentence. Short steps ("Go to Settings > Leave.") are never restatements.
# ---------------------------------------------------------------------------
# Instructions anywhere in a reply: only the KB entry may back them
# ---------------------------------------------------------------------------
# A sentence or line that tells the customer to do something ("Try
# restarting the app", "Have you tried disabling the firewall?", "If it's
# missing, click Export") must be backed by ONE passage of the KB entry
# (a sentence or step, or two adjacent ones): the passage has its action
# verb and most of its content words. Never by the customer's own words:
# "should I disable the firewall?" makes "disable the firewall" no safer.
_ACTION_VERBS = """open click tap select choose go navigate enable disable turn toggle restart reboot reinstall
    install uninstall clear delete remove add update upgrade check verify sign log set change edit copy paste allow
    block contact reach refresh reload reset search download upload configure whitelist use type enter press submit
    attach save cancel apply export import pick drag scroll wait visit""".split()
_INSTRUCTION_LEAD = re.compile(
    r"^(?:(?:if|when|once|to|for|after|before)\b[^,]{0,120},\s*)?"
    r"(?:(?:please|so|then|next|also|first|finally|now|just)\b,?\s*)*"
    r"(?:(?:have you tried|did you try|could you try|can you try|you (?:can|could|should|need to|must|may want to"
    r"|might want to|will need to))\s+|(?:try|make sure (?:to|that you)?|ensure (?:that )?(?:you )?)\s+)?"
    r"(?:(?:also|just|then|simply|first|now)\b,?\s*)*",
    re.IGNORECASE)
INSTRUCTION_SUPPORT = 0.5
# Verbs that name the same action in a paraphrase ("choose the leave type"
# for the KB's "pick the leave type"); any other action verb is its own group.
_VERB_GROUPS = [
    "open go navigate visit access head",
    "select choose pick",
    "click tap press hit",
    "check verify look search find inspect confirm see review",
    "enable allow turn permit grant",
    "install download get",
    "type enter fill",
    "submit send save",
]


# Generic UI nouns: "click the Submit button" is "click Submit".
_UI_NOUNS = frozenset("button page option field section screen tab link menu item list".split())
INSTRUCTION_RESTATES = 0.8   # nearly every word in one passage: the verb may differ ("use X" / "X is")


def _verb(word: str) -> str:
    """Comparable form of a verb: "disable", "disabling", "disabled" alike."""
    word = word.lower().split("-")[-1]
    word = word[:-3] if word.endswith("ing") and len(word) > 4 else _stem(word)
    return word[:-1] if word.endswith("e") else word


_ACTIONS = frozenset(_verb(w) for w in _ACTION_VERBS)
_GROUP = {_verb(w): n for n, group in enumerate(_VERB_GROUPS) for w in group.split()}


def _same_action(verb: str, word: str) -> bool:
    word = _verb(word)
    return word == verb or (verb in _GROUP and _GROUP.get(word) == _GROUP[verb])


def instruction_verb(sentence: str) -> str | None:
    """The action verb when `sentence` tells the customer to do something."""
    rest = _INSTRUCTION_LEAD.sub("", sentence.strip(), count=1)
    match = re.match(r"[A-Za-z]+(?:-[A-Za-z]+)?", rest)
    verb = _verb(match.group(0)) if match else ""
    return verb if verb in _ACTIONS or verb in _GROUP else None


# Sentence ends, but never after a bare step number ("1. Open Leave. 2. Pick...").
_SENTENCE_BREAK = re.compile(r"(?<=[^\d\s][.!?])\s+")
STEP_NUMBER = re.compile(r"(?:^|\s)\d+[.)]\s")


def _passages(kb: str) -> list[str]:
    units = [u.strip() for line in kb.splitlines() for u in _SENTENCE_BREAK.split(_STEP_LINE.sub(r"\4", line))
             if u.strip()]
    return units + [f"{a} {b}" for a, b in zip(units, units[1:])]


def instruction_supported(sentence: str, kb: str) -> bool:
    verb = instruction_verb(sentence)
    if verb is None:
        return True
    from backend import product   # lazy: settings import categories

    words = content_words(sentence) - _UI_NOUNS - {_stem(w) for w in product.name_words()}
    looking = _GROUP.get(verb) == _GROUP[_verb("check")]   # looking for what the KB names
    for passage in _passages(kb):
        share = len(words & content_words(passage)) / len(words) if words else 1.0
        if share >= INSTRUCTION_RESTATES:
            return True
        if share >= INSTRUCTION_SUPPORT and (looking or any(_same_action(verb, w)
                                                             for w in _WORD.findall(passage.lower()))):
            return True
    return False


def ground_instructions(text: str, kb: str) -> tuple[str, list[str]]:
    """`text` without the instructions the KB entry doesn't back (code
    blocks untouched; numbered steps renumbered). Returns the text and the
    dropped instructions."""
    out, dropped, number, fenced = [], [], 0, False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append(line)
            continue
        if fenced or not line.strip():
            out.append(line)
            continue
        step = _STEP_LINE.match(line)
        units = [step.group(4)] if step else _SENTENCE_BREAK.split(line.strip())
        kept = [u for u in units if instruction_supported(re.sub(r"^\d+[.)]\s+", "", u), kb) or dropped.append(u)]
        if not kept:
            continue
        if step:
            indent, marker, space, _ = step.groups()
            if marker[0].isdigit():
                number += 1
                marker = f"{number}{marker[-1]}"
            out.append(f"{indent}{marker}{space}{kept[0]}")
        else:
            out.append(" ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip(), dropped


RESTATES = 0.6
_RESTATE_MIN_WORDS = 5


def drop_restatements(text: str) -> tuple[str, list[str]]:
    """`text` without sentences and step lines that restate an earlier
    prose sentence (code blocks untouched); numbered steps are renumbered.
    Returns the text and the dropped sentences."""
    out, dropped, seen, number, fenced = [], [], [], 0, False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        step = _STEP_LINE.match(line)
        if fenced or line.lstrip().startswith("```") or not line.strip():
            out.append(line)
            continue
        kept = []
        for unit in [step.group(4)] if step else _SENTENCE_END.split(line.strip()):
            words = content_words(unit)
            if len(words) >= _RESTATE_MIN_WORDS and any(len(words & s) / len(words) >= RESTATES for s in seen):
                dropped.append(unit)
                continue
            kept.append(unit)
            if not step:
                seen.append(words)
        if not kept:
            continue
        if step:
            indent, marker, space, _ = step.groups()
            if marker[0].isdigit():
                number += 1
                marker = f"{number}{marker[-1]}"
            out.append(f"{indent}{marker}{space}{kept[0]}")
        else:
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
