"""The eval's database, KB and counted model client."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections import Counter
from pathlib import Path

# The provider lets it through (never turned into "AI unavailable").
from backend.ai_service.backends import CallCapReached as CapReached

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".local" / "chat-eval"
DEMO_DB = ROOT / "backend" / "ticketapp.db"
BRIGHTDESK = ROOT / "tests" / "fixtures" / "kb" / "brightdesk.json"
LEDGER = OUT / "ledger.json"

NOVA_LITE = "apac.amazon.nova-lite-v1:0"
NOVA_PRO = "apac.amazon.nova-pro-v1:0"
# USD per 1M tokens (in, out), Bedrock list prices.
PRICES = {"nova-lite": (0.071, 0.284), "nova-pro": (0.94, 3.76)}


def prepare_env(bot_model: str) -> None:
    """Before the backend is imported: a quiet, unlimited, local app."""
    os.environ.update({
        "AI_PROVIDER": "bedrock", "BEDROCK_MODEL_ID": NOVA_LITE, "BEDROCK_MODEL_ID_CHAT": bot_model,
        "AI_RATE_LIMIT_ENABLED": "false", "SIGNUP_RATE_LIMIT_ENABLED": "false",
        "LOGIN_RATE_LIMIT_ENABLED": "false", "CUSTOMER_SIGNUP_ENABLED": "true", "EMAIL_ENABLED": "false",
        "DB_BACKEND": "sqlite", "APP_ENV": "development",
    })
    os.environ.setdefault("EVAL_CUSTOMER_MODEL", NOVA_LITE)
    os.environ.setdefault("EVAL_JUDGE_MODEL", NOVA_PRO)


def load_pack(kb: str) -> tuple[dict, dict]:
    """(pack, product profile) for "demo" (the approved KB of the local
    database) or "brightdesk" (the neutral test fixture)."""
    if kb == "brightdesk":
        data = json.loads(BRIGHTDESK.read_text(encoding="utf-8"))
        return {"terms": data["terms"], "entries": data["entries"]}, data["product"]
    from backend import kb_store

    conn = sqlite3.connect(f"file:{DEMO_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        pack = kb_store.export_pack(conn)
        row = conn.execute("SELECT value FROM app_settings WHERE key = 'product'").fetchone()
    finally:
        conn.close()
    return pack, (json.loads(row["value"]) if row else {})


def open_app(db_path: Path, pack: dict, product: dict):
    """A started TestClient on a new database holding the pack."""
    from fastapi.testclient import TestClient

    from backend import app_settings, db, incidents, kb_store, main

    db.DB_PATH = db_path
    incidents.run_for_ticket = lambda ticket_id: None   # not under test; would spend calls
    client = TestClient(main.app)
    client.__enter__()
    conn = db.get_connection()
    try:
        kb_store.import_pack(conn, pack, "eval")
        if product:
            app_settings.save(conn, "product", product, "eval")
        conn.commit()
    finally:
        conn.close()
    kb_store.changed()
    return client


class CountedClient:
    """Wraps the bedrock-runtime client: counts every real call (retries
    included) per model, refuses calls past the cap, adds up tokens."""

    def __init__(self, inner, cap: int):
        self.inner, self.cap = inner, cap
        self.calls, self.tokens_in, self.tokens_out = Counter(), Counter(), Counter()
        self._lock = threading.Lock()

    @property
    def total(self) -> int:
        return sum(self.calls.values())

    def converse(self, **request):
        model = "nova-pro" if "nova-pro" in request.get("modelId", "") else "nova-lite"
        with self._lock:
            if self.total >= self.cap:
                raise CapReached(f"call cap {self.cap} reached")
            self.calls[model] += 1
        response = self.inner.converse(**request)
        usage = response.get("usage", {})
        with self._lock:
            self.tokens_in[model] += usage.get("inputTokens", 0)
            self.tokens_out[model] += usage.get("outputTokens", 0)
        return response

    def cost(self) -> float:
        return sum(self.tokens_in[m] / 1e6 * PRICES[m][0] + self.tokens_out[m] / 1e6 * PRICES[m][1]
                   for m in PRICES)

    def summary(self) -> dict:
        return {"calls": dict(self.calls), "total_calls": self.total, "tokens_in": dict(self.tokens_in),
                "tokens_out": dict(self.tokens_out), "cost_usd": round(self.cost(), 4)}


def install_counted_backend(cap: int) -> CountedClient:
    from backend.ai_service import provider
    from backend.ai_service.backends import BedrockBackend

    counted = CountedClient(BedrockBackend().client(), cap)
    provider.set_backend(BedrockBackend(client=counted))
    return counted


def ledger() -> dict:
    try:
        return json.loads(LEDGER.read_text())
    except (OSError, ValueError):
        return {"spent": 0, "cost_usd": 0.0, "runs": []}


def record(run_id: str, summary: dict) -> dict:
    data = ledger()
    data["spent"] += summary["total_calls"]
    data["cost_usd"] = round(data["cost_usd"] + summary["cost_usd"], 4)
    data["runs"].append({"run": run_id, **summary})
    OUT.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(data, indent=2))
    return data
