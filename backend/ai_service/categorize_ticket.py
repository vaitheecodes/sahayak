"""categorize_ticket: one of the confirmed categories plus a confidence.

Raw model judgement only; the routing graph (backend/graph.py) combines it
with KB retrieval and applies the routing policy. An unknown category or
an out-of-range confidence fails validation instead of being guessed at.
"""

from __future__ import annotations

from backend import categories, product
from backend.ai_service import provider
from backend.ai_service._format import candidates_text, history_text
from backend.ai_service.schemas import Categorization, CategorizeInput, with_categories


def _categories_text() -> str:
    return "\n".join(f"- {c['name']}: {c['label']}" + (f" ({c['description']})" if c["description"] else "")
                     for c in categories.described())


def categorize_ticket(data: CategorizeInput) -> Categorization:
    return provider.complete_json(
        f"You classify support tickets for {product.described()} into exactly one "
        "of the categories in the categories block (answer with its name). The "
        "kb_matches block lists the closest real KB entries; treat a close wording "
        "match there as strong evidence for that entry's category, even for a short "
        "or casually phrased ticket. confidence is how sure you are (0.0-1.0) that "
        "the category is right.",
        {
            "categories": _categories_text(),
            "customer_history": history_text(data.history, with_status=True),
            "kb_matches": candidates_text(data.kb_candidates),
            "ticket": data.ticket_text,
        },
        with_categories(Categorization, categories.names()),
    )
