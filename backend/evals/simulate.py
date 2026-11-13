"""One conversation: the case's opener, then fixed or simulated customer
turns against the real /api/chats endpoints, until the chat closes, is
escalated, or the case's turns are used."""

from __future__ import annotations

import itertools
import threading

from pydantic import BaseModel, Field

from backend.ai_service import AIError
from backend.evals.cases import Case
from backend.evals.harness import CapReached

_counter = itertools.count()
_counter_lock = threading.Lock()

_CUSTOMER = (
    "You play a customer chatting with a product's help-desk bot. Stay in character: {persona}. Your goal: "
    "{goal}. Read the conversation and write your next message, short (one to three sentences), reacting to "
    "the bot's last reply: answer its question if it asked one (make up plausible details about your own "
    "situation, never about the product), ask about anything unclear, or say what didn't work. Set done to "
    "true when your goal is met or the bot has handed you to a person."
)


class _CustomerTurn(BaseModel):
    message: str = Field(description="your next message to the bot")
    done: bool = False


def _signup(client) -> dict:
    with _counter_lock:
        n = next(_counter)
    res = client.post("/api/auth/customer/signup", json={
        "name": "Eval Customer", "email": f"eval-{n}@example.com", "password": "eval-pass-123"})
    res.raise_for_status()
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _bot_messages(view: dict) -> list[str]:
    """The bot's messages after the customer's last one."""
    out = []
    for message in reversed(view.get("messages") or []):
        if message["role"] == "customer":
            break
        out.append(message["content"])
    return out[::-1]


def _next_message(case: Case, turns: list[dict]) -> _CustomerTurn:
    from backend.ai_service import backends, provider

    transcript = "\n".join(f"Customer: {t['customer']}\nBot: {t['bot']}" for t in turns)
    with backends.model_task("eval_customer"):
        return provider.complete_json(_CUSTOMER.format(persona=case.persona, goal=case.goal or "get help"),
                                      {"conversation": transcript}, _CustomerTurn, temperature=0.7,
                                      operation="eval_customer")


def run(client, case: Case) -> dict:
    """{case, turns: [{customer, bot, status, ticket_id, ai_error}], issue, error}"""
    headers = _signup(client)
    turns: list[dict] = []
    result = {"case": case.model_dump(), "turns": turns, "issue": None, "error": None}
    message, session_id = case.opener, None
    try:
        for n in range(case.turns):
            if session_id is None:
                res = client.post("/api/chats", json={"issue": message}, headers=headers)
            else:
                res = client.post(f"/api/chats/{session_id}/messages", json={"message": message}, headers=headers)
            if res.status_code != 200:
                turns.append({"customer": message, "bot": "", "status": None, "ticket_id": None,
                              "ai_error": f"HTTP {res.status_code}"})
                break
            view = res.json()
            session_id = result["session_id"] = view["session_id"]
            result["issue"] = view.get("issue")
            bot = _bot_messages(view)
            turns.append({"customer": message, "bot": "\n\n".join(bot), "bot_messages": bot, "status": view["status"],
                          "ticket_id": view.get("ticket_id"), "ai_error": view.get("ai_error")})
            if view["status"] != "active" or n + 1 >= case.turns:
                break
            if n < len(case.script):
                message = case.script[n]
            elif case.simulate:
                nxt = _next_message(case, turns)
                if nxt.done:
                    break
                message = nxt.message
            else:
                break
    except CapReached as exc:
        result["error"] = str(exc)
    except AIError as exc:   # the simulated customer's own call failed: not the bot's fault
        result["error"] = f"simulator: {exc}"
    return result
