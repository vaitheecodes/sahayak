"""The judge model (EVAL_JUDGE_MODEL, Nova Pro by default): one call per
conversation, a short rubric, structured verdicts. Rule 1 judge failures
are judged a second time; what both calls flag is disputed (for a human)."""

from __future__ import annotations

from pydantic import BaseModel, Field

_RUBRIC = (
    "You review a conversation between a customer and a product's help-desk bot. The bot may only use the "
    "knowledge-base entries given and what the customer said. Judge strictly but fairly:\n"
    "- invented: every step, setting, value, domain, number or factual claim about the product in the bot's "
    "replies that is NOT supported by the knowledge-base entries or the customer's own messages. Generic "
    "politeness, questions to the customer, and offers to raise a ticket are not claims. Rephrasing a "
    "supported step is not invention. Empty list when nothing is invented.\n"
    "- covered: true when one of the entries answers the customer's main question (not just a related topic).\n"
    "- helpful (1-5): did the replies move the customer forward as far as the entries allow?\n"
    "- tone (1-5): plain, kind, brief, no blame, polite with angry or off-topic customers.\n"
    "- note: one sentence on the main problem, or empty."
)


class Verdict(BaseModel):
    invented: list[str] = Field(default_factory=list)
    covered: bool
    helpful: int = Field(ge=1, le=5)
    tone: int = Field(ge=1, le=5)
    note: str = ""


def _entries_text(pack: dict) -> str:
    from backend.evals.cases import _entry_text

    return "\n\n".join(_entry_text(e) + (f"\nSnippets: {e.get('snippets')}" if e.get("snippets") else "")
                       for e in pack["entries"])


def judge(result: dict, pack: dict) -> Verdict:
    from backend.ai_service import backends, provider

    conversation = "\n".join(f"Customer: {t['customer']}\nBot: {t['bot']}" for t in result["turns"])
    with backends.model_task("eval_judge"):
        return provider.complete_json(_RUBRIC, {"knowledge_base": _entries_text(pack),
                                                "conversation": conversation}, Verdict, operation="eval_judge")
