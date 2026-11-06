"""The neutral test KB: "Brightdesk HR", a fictional HR product
(tests/fixtures/kb/brightdesk.json).

load() puts it in memory, the way the app sees an approved KB: its
entries searched by kb_retrieval, its terms confirmed in topic_terms and
its product profile in app_settings (the app's startup reloads settings,
so call it after a TestClient has started). Tests of the database path import it
with kb_store.import_pack instead.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend import app_settings, kb_retrieval, topic_terms  # noqa: F401  (topic_terms: tests reset it)

PACK_PATH = Path(__file__).resolve().parent / "fixtures" / "kb" / "brightdesk.json"


def pack() -> dict:
    return json.loads(PACK_PATH.read_text(encoding="utf-8"))


def load() -> dict:
    data = pack()
    kb_retrieval.use(data["entries"])
    topic_terms.use(data["terms"])
    app_settings._overrides["product"] = data["product"]
    return data


def entry(kb_entry_id: str) -> dict:
    return next(e for e in pack()["entries"] if e["kb_entry_id"] == kb_entry_id)


def candidate(kb_entry_id: str, question: int = 0, score: float = 0.9) -> dict:
    """An entry as graph.kb_candidates_for returns it."""
    from backend import kb_store

    doc = kb_store.retrieval_docs([entry(kb_entry_id)])[question]
    return {**doc, "score": score}
