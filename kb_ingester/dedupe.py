"""Near-duplicate flagging: is a new draft about the same thing as an
entry that already exists (draft or approved, any source)?

Each entry is one document: its title, questions and answer. Documents
are TF-IDF weighted over the existing entries plus the new one and
compared by cosine; the best match at DUPLICATE_SCORE or above is
returned. Only a flag for the reviewer: nothing is merged or dropped.
"""

from __future__ import annotations

import math
from collections import Counter

from backend.kb_retrieval import tokenize

DUPLICATE_SCORE = 0.8


def _text(entry: dict) -> str:
    return " ".join([entry.get("title") or "", *(entry.get("questions") or []), entry.get("answer") or "",
                     *(s.get("text", "") for s in entry.get("steps") or [])])


def best_match(entry: dict, existing: list[dict]) -> tuple[str, float] | None:
    """(kb_entry_id, score) of the closest existing entry, or None."""
    docs = [Counter(tokenize(_text(e))) for e in existing]
    new = Counter(tokenize(_text(entry)))
    if not new or not docs:
        return None
    count = len(docs) + 1
    df = Counter(t for doc in [*docs, new] for t in doc)
    idf = {t: math.log((1 + count) / (1 + n)) + 1 for t, n in df.items()}

    def vector(doc: Counter) -> dict[str, float]:
        return {t: c * idf[t] for t, c in doc.items()}

    target = vector(new)
    norm = math.sqrt(sum(v * v for v in target.values()))
    best = None
    for e, doc in zip(existing, docs):
        vec = vector(doc)
        other = math.sqrt(sum(v * v for v in vec.values()))
        if not other:
            continue
        score = sum(w * vec.get(t, 0.0) for t, w in target.items()) / (norm * other)
        if best is None or score > best[1]:
            best = (e["kb_entry_id"], round(score, 3))
    return best if best and best[1] >= DUPLICATE_SCORE else None
