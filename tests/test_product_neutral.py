"""The core is product-neutral: Sahayak doesn't know the client's product.

- Categories are data (kb_categories): seeded once with neutral defaults,
  extended without code, used by the classifier's schema, departments,
  the routing settings, the category pickers and /api/meta.
- The product profile (app_settings "product") names the product in
  prompts; without one, prompts say "the product". The admin sets it in
  Settings.
- No product name, KB data or product-specific vocabulary is left in the
  code, prompts, migrations, scripts or frontend.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import app_settings, categories, db, main, product
from backend.ai_service import categorize_ticket, chat_response, provider, schemas
from backend.ai_service.schemas import AnswerInput, CategorizeInput

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    with TestClient(main.app) as c:
        yield c


def _admin(client):
    res = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "admin-dev-password"})
    return {"Authorization": f"Bearer {res.json()['token']}"}


# ---------------------------------------------------------------------------
# Categories are data
# ---------------------------------------------------------------------------
def test_a_new_database_is_seeded_with_the_neutral_categories_once(client):
    names = [c[0] for c in categories.DEFAULT_CATEGORIES]
    assert client.get("/api/categories").json() == sorted(names)
    conn = db.get_connection()
    try:
        categories.seed(conn)  # again: nothing added
        assert conn.execute("SELECT COUNT(*) FROM kb_categories").fetchone()[0] == len(names)
    finally:
        conn.close()
    meta = client.get("/api/meta").json()
    assert meta["category_labels"]["ISSUE"] == "Something isn't working"
    assert meta["kb_entries"] == 0


def test_a_new_category_is_used_everywhere_without_code(client):
    conn = db.get_connection()
    try:
        categories.add(conn, "PAYROLL", "Payroll", "Salaries and payslips")
        categories.add(conn, "TIMESHEETS", "Timesheets", status="proposed", source="ingest")
        conn.commit()
    finally:
        conn.close()
    assert "PAYROLL" in client.get("/api/categories").json()
    assert "TIMESHEETS" not in categories.names()  # proposed: not used until confirmed
    admin = _admin(client)
    res = client.post("/api/admin/departments", json={"name": "Payroll Team", "categories": ["PAYROLL"]},
                      headers=admin)
    assert res.status_code == 200, res.text
    res = client.put("/api/admin/settings/routing", json={"high_risk_categories": ["PAYROLL"]}, headers=admin)
    assert res.status_code == 200 and res.json()["sections"]["routing"]["high_risk_categories"] == ["PAYROLL"]
    schema = schemas.with_categories(schemas.Categorization, categories.names()).model_json_schema()
    assert "PAYROLL" in schema["properties"]["category"]["enum"]


def test_an_unknown_category_is_refused(client):
    res = client.put("/api/admin/settings/routing", json={"high_risk_categories": ["MONITORING"]},
                     headers=_admin(client))
    assert res.status_code == 422


@pytest.mark.parametrize("name", ["", "payroll", "1PAY", "PAY ROLL", "A" * 50])
def test_category_names_are_checked(name):
    assert categories.problem(name)


def test_the_classifier_sees_the_categories_and_may_only_pick_one(monkeypatch):
    seen = {}

    def fake(messages, **kwargs):
        seen["system"], seen["user"], seen["kwargs"] = messages[0]["content"], messages[1]["content"], kwargs
        return '{"category": "NOT_A_CATEGORY", "confidence": 0.9}'

    monkeypatch.setattr(provider, "complete", fake)
    with pytest.raises(provider.AIError):  # outside the listed names: invalid, retried, then an error
        categorize_ticket.categorize_ticket(CategorizeInput(ticket_text="my payslip is missing"))
    assert "- ISSUE: Something isn't working (Errors and unexpected behaviour)" in seen["user"]
    categories.use([{"name": "PAYROLL", "label": "Payroll", "description": ""}])
    monkeypatch.setattr(provider, "complete", lambda messages, **k: '{"category": "PAYROLL", "confidence": 0.9}')
    assert categorize_ticket.categorize_ticket(CategorizeInput(ticket_text="x")).category == "PAYROLL"


def test_the_default_high_risk_categories_follow_the_categories():
    assert app_settings.get("routing").high_risk_categories == ["ACCOUNT", "BILLING", "DATA"]
    categories.use([{"name": "ACCOUNT", "label": "Account", "description": ""}])
    assert app_settings.get("routing").high_risk_categories == ["ACCOUNT"]


# ---------------------------------------------------------------------------
# The product profile
# ---------------------------------------------------------------------------
def _answer_prompt(monkeypatch) -> str:
    seen = {}

    def fake(instructions, data, **kwargs):
        seen["instructions"] = instructions
        return "An answer."

    monkeypatch.setattr(provider, "complete_text", fake)
    chat_response.answer(AnswerInput(ticket_text="Customer: how do I apply for leave"))
    return seen["instructions"]


def test_without_a_product_name_prompts_say_the_product(monkeypatch):
    assert product.name() == "the product" and product.described() == "the product"
    assert "support assistant for the product," in _answer_prompt(monkeypatch)


def test_the_admin_names_the_product_and_prompts_use_it(client, monkeypatch):
    res = client.put("/api/admin/settings/product", json={
        "name": "Brightdesk HR", "description": "an HR management system", "support_team_name": "Brightdesk Support"},
        headers=_admin(client))
    assert res.status_code == 200, res.text
    assert client.get("/api/meta").json()["product"] == {"name": "Brightdesk HR",
                                                         "support_team_name": "Brightdesk Support"}
    assert "support assistant for Brightdesk HR (an HR management system)," in _answer_prompt(monkeypatch)
    assert chat_response.clean_chat_reply("Open Leave.\nBrightdesk Support") == "Open Leave."


def test_the_product_name_alone_is_vague():
    from backend import graph

    app_settings._overrides["product"] = {"name": "Brightdesk HR"}
    assert graph.is_vague("Customer: I have a problem with Brightdesk HR")
    assert not graph.is_vague("Customer: my payslip is missing")


# ---------------------------------------------------------------------------
# Nothing product-specific in code
# ---------------------------------------------------------------------------
_PRODUCT_WORDS = re.compile(r"site24x7|\bmonitors?\b|\bmonitoring\b|\bAPM\b|\bSNMP\b|\bNetFlow\b|pagerduty",
                            re.IGNORECASE)
# The theme menu's "System" icon is lucide's Monitor (a screen).
_ALLOWED = re.compile(r"\bMonitor(Icon)?\b(?=[,}\s]|\(|$)|lucide-react|\[\"system\"")


def _tracked(*paths: str) -> list[Path]:
    out = subprocess.run(["git", "ls-files", *paths], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.splitlines() if (ROOT / line).is_file()]


# The product-neutral core. Only these are checked: a separate tool
# outside the core (a future monitoring tool in monitor/) may use the
# words, and so may tests.
CORE = ("backend", "kb_ingester", "scripts", "migrations", "frontend/src", "Dockerfile")


def test_no_product_words_in_the_code_prompts_migrations_or_frontend():
    found = []
    files = _tracked(*CORE)
    files += [p for d in ("backend", "kb_ingester") for p in (ROOT / d).rglob("*.py")]
    files += list((ROOT / "migrations" / "postgres").glob("*.sql"))
    for path in sorted(set(files)):
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            if _PRODUCT_WORDS.search(line) and not (path.suffix in (".jsx", ".js") and _ALLOWED.search(line)):
                if path.name == "0001_initial.sql":  # the first schema, applied as it was
                    continue
                found.append(f"{path.relative_to(ROOT)}:{number}")
    assert found == []


def test_the_ban_is_limited_to_the_core():
    assert "monitor" not in CORE and not any(c.startswith("monitor/") for c in CORE)


def test_no_kb_data_ships_with_the_code():
    assert not (ROOT / "data").exists() or not any((ROOT / "data").rglob("*.json"))
    assert _tracked("data") == []
