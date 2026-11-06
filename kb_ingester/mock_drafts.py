"""What the offline mock AI provider drafts (AI_PROVIDER=mock).

Without a model the mock backend would return empty drafts, and a local
run would show nothing to review. These responders draft one entry per
chunk from its own text: the title is the section heading, each numbered
or bulleted line becomes a step quoting itself, and every step is
"supported". The output still goes through all of drafting.py's checks.
It is a stand-in for trying the flow, not a drafter: the questions and
answer are templates.
"""

from __future__ import annotations

import json
import re

from backend import categories
from backend.ai_service import backends

_BLOCK = re.compile(r"<(?P<name>[a-z_]+)>\n(?P<body>.*?)\n</(?P=name)>", re.DOTALL)
_ITEM = re.compile(r"^\s*(?:\d+\.|[-*+])\s+(.{15,300}?)\s*$", re.MULTILINE)


def _blocks(user_content: str) -> dict[str, str]:
    return {m.group("name"): m.group("body") for m in _BLOCK.finditer(user_content)}


def draft(system_prompt: str, user_content: str) -> dict:
    blocks = _blocks(user_content)
    chunk = blocks.get("source_chunk", "")
    section = blocks.get("page", "").rpartition("Section: ")[2].strip()
    heading = section.split(" > ")[-1] if section and section != "(top of page)" else ""
    first = re.search(r"^#{1,3} (.+)$", chunk, re.M)
    title = (heading or (first.group(1) if first else "") or "Untitled section").strip()[:120]
    steps = [{"text": item.strip(), "quote": item.strip()} for item in _ITEM.findall(chunk)][:12]
    names = categories.names()
    category = "USAGE" if "USAGE" in names else names[0]
    subject = title[0].lower() + title[1:] if title else "this"
    return {"entries": [{
        "title": title,
        "questions": [f"How do I {subject}?", f"Where can I find {subject}?", f"Can you help me with {subject}?"],
        "answer": f"A draft from the offline mock provider about {subject}. Rewrite it before approving.",
        "kind": "how-to" if steps else "troubleshooting",
        "steps": steps, "applies_to": [], "category": category,
    }], "proposed_terms": [], "proposed_categories": []}


def check_support(system_prompt: str, user_content: str) -> dict:
    try:
        steps = json.loads(_blocks(user_content).get("steps_to_check", "[]"))
    except ValueError:
        steps = []
    return {"verdicts": [{"id": s["id"], "supported": True} for s in steps if isinstance(s, dict) and "id" in s]}


backends.MOCK_RESPONDERS["DraftedEntries"] = draft
backends.MOCK_RESPONDERS["StepSupport"] = check_support
