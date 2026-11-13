"""rewrite_query: when the KB search finds nothing close, the customer's
message in the knowledge base's own words, so the same search can find
the guide it means ("update my browser's stored pages" -> "clear cached
pages"). The model only rewrites the query: the rewrite still has to score
above KB_MIN_SCORE, and every later check (terms, how-to subject,
NOT_COVERED, grounding) still applies. "" when no topic is about the same
thing."""

from __future__ import annotations

from backend import product
from backend.ai_service import provider
from backend.ai_service.schemas import RewrittenQuery

MAX_TOPICS = 150


def rewrite_query(message: str, topics: list[str]) -> str:
    result = provider.complete_json(
        f"A customer of {product.described()} wrote the message below. The help desk's knowledge base has "
        "the topics listed. If one topic is about the same thing the customer means, rewrite the message as a "
        "short search query (at most 12 words) in that topic's own words. Never add a task, setting or product "
        "area the customer didn't mean. If no topic is about the same thing, return an empty query.",
        {"customer_message": message, "kb_topics": "\n".join(topics[:MAX_TOPICS])},
        RewrittenQuery, operation="rewrite_query")
    return result.query.strip()
