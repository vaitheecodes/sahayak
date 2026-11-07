"""Drafting-quality fixes: numbered lists read by code, the completeness
flag and its acknowledgement, a model per operation, and the source's
licence note on entries. Fixture pages: tests/fixtures/kb/pages/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import app_settings, db, kb_store, main
from backend.ai_service import backends
from kb_ingester import chunking, clean
from kb_ingester.steps import ordered_lists
from tests.kb_ingest_helpers import LEAVE_PAGE, FakeWeb, ScriptedModel, http_response, leave_drafts, use_web
from tests.test_kb_ingest_api import URL, _login, _run, _source

PAGES = Path(__file__).parent / "fixtures" / "kb" / "pages"


# ---------------------------------------------------------------------------
# Numbered lists
# ---------------------------------------------------------------------------
def test_ordered_lists_are_read_in_order_with_their_nested_lines():
    text = ("Intro\n\n1. First.\n2. Second.\n  - detail a\n  1. sub step\n3. Third.\n\nProse.\n\n"
            "1. Other list one.\n2. Other list two.\n\n- a bullet\n1. Lonely item.\n\n5. Five.\n6. Six.")
    assert ordered_lists(text) == [
        ["First.", "Second.\n  - detail a\n  1. sub step", "Third."],
        ["Other list one.", "Other list two."],
        ["Five.", "Six."],
    ]


def test_a_numbering_gap_starts_a_new_list_and_single_items_are_ignored():
    assert ordered_lists("1. a\n2. b\n4. d\n5. e") == [["a", "b"], ["d", "e"]]
    assert ordered_lists("1. only one") == []


def _fixture_chunks(name):
    page = clean.html_to_text((PAGES / f"{name}.html").read_bytes())
    return chunking.chunk_text(page.text)[0]


def test_fixture_pages_have_their_expected_ordered_steps():
    expected = json.loads((PAGES / "expected.json").read_text())["pages"]
    for name, spec in expected.items():
        found = [len(items) for chunk in _fixture_chunks(name) for items in ordered_lists(chunk.text)]
        assert found == spec["ordered_lists"], name


def test_the_github_procedure_keeps_its_first_and_last_steps_and_nested_options():
    [items] = ordered_lists(_fixture_chunks("github_new_repository")[0].text)
    assert items[0] == "In the upper-right corner of any page, select, then click New repository."
    assert items[9] == "Click Create repository."
    assert "  - You can create a .gitignore file" in items[6]


# ---------------------------------------------------------------------------
# Model per operation
# ---------------------------------------------------------------------------
def test_each_drafting_operation_can_run_on_its_own_bedrock_model(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    app_settings._overrides["ai_models"] = {"draft_kb_entries": "apac.amazon.nova-pro-v1:0"}
    with backends.model_task("draft_kb_entries"):
        assert backends.BedrockBackend.model_id() == "apac.amazon.nova-pro-v1:0"
    with backends.model_task("check_step_support"):
        assert backends.BedrockBackend.model_id() == "apac.amazon.nova-lite-v1:0"
    assert backends.BedrockBackend.model_id() == "apac.amazon.nova-lite-v1:0"


def test_drafting_runs_under_its_model_task(monkeypatch):
    seen = []

    def fake(messages, **kwargs):
        seen.append(backends._model_task.get())
        return json.dumps({"entries": [], "proposed_terms": []}) if "draft" in messages[0]["content"] else "{}"

    from backend.ai_service import draft_kb_entries as op, provider
    from backend.ai_service.schemas import DraftInput

    monkeypatch.setattr(provider, "complete", fake)
    op.draft_kb_entries(DraftInput(chunk_text="Some text."))
    assert seen == ["draft_kb_entries"]


@pytest.mark.parametrize("value", ["apac.amazon.nova-pro-v1:0", "", "arn:aws:bedrock:ap-south-1:1:inference-profile/x"])
def test_model_ids_are_validated(value):
    assert app_settings.AIModelSettings(draft_kb_entries=value).draft_kb_entries == value


def test_a_bad_model_id_is_refused():
    with pytest.raises(ValueError):
        app_settings.AIModelSettings(draft_kb_entries="nova pro; drop table")


# ---------------------------------------------------------------------------
# Completeness flag and licence note, end to end
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def manager(client):
    return _login(client, "manager")


@pytest.fixture()
def web(monkeypatch):
    web = FakeWeb().host("help.example.com").page("help.example.com", "/leave", http_response(LEAVE_PAGE))
    return use_web(monkeypatch, web)


def test_an_entry_missing_list_steps_is_flagged_and_needs_an_acknowledgement(client, manager, web, monkeypatch):
    ScriptedModel(leave_drafts, supported=lambda step, quote: "dates" not in step.lower()).install(monkeypatch)
    _run(client, manager, _source(client, manager))
    [row] = client.get("/api/kb/entries?flag=incomplete", headers=manager).json()["entries"]
    assert row["completeness"] == {"kept": 2, "expected": 3} and "incomplete" in row["flags"]
    entry_id, version = row["kb_entry_id"], row["version"]
    res = client.post(f"/api/kb/entries/{entry_id}/approve", headers=manager, json={"version": version})
    assert res.status_code == 409 and "2 of 3" in res.json()["detail"]
    res = client.post(f"/api/kb/entries/{entry_id}/approve", headers=manager,
                      json={"version": version, "acknowledge_incomplete": True})
    assert res.status_code == 200 and res.json()["status"] == "approved"
    conn = db.get_connection()
    try:
        detail = conn.execute("SELECT detail FROM audit_events WHERE action = 'kb.entry.approve'").fetchone()[0]
    finally:
        conn.close()
    assert json.loads(detail)["acknowledged_incomplete"] == {"kept": 2, "expected": 3}


def test_a_complete_entry_needs_no_acknowledgement(client, manager, web, monkeypatch):
    ScriptedModel(leave_drafts).install(monkeypatch)
    _run(client, manager, _source(client, manager))
    [row] = client.get("/api/kb/entries", headers=manager).json()["entries"]
    assert row["completeness"] is None and "incomplete" not in row["flags"]
    detail = client.get(f"/api/kb/entries/{row['kb_entry_id']}", headers=manager).json()
    assert [s["quote"] for s in detail["steps"]][0] == "Open the Leave module from the left menu."
    res = client.post(f"/api/kb/entries/{row['kb_entry_id']}/approve", headers=manager,
                      json={"version": row["version"]})
    assert res.status_code == 200


def test_an_unchanged_long_item_quote_survives_an_edit(client, manager, web, monkeypatch):
    long_item = "Pick the start and end dates, then click Submit. " + "Extra detail here. " * 30
    page = LEAVE_PAGE.replace("Pick the start and end dates, then click Submit.", long_item)
    web.page("help.example.com", "/leave", http_response(page))
    ScriptedModel(leave_drafts).install(monkeypatch)
    _run(client, manager, _source(client, manager))
    detail = client.get(f"/api/kb/entries/{client.get('/api/kb/entries', headers=manager).json()['entries'][0]['kb_entry_id']}",
                        headers=manager).json()
    assert len(detail["steps"][2]["quote"]) > 500
    res = client.patch(f"/api/kb/entries/{detail['kb_entry_id']}", headers=manager,
                       json={"version": detail["version"], "title": "Book leave",
                             "steps": [{"text": s["text"], "quote": s["quote"]} for s in detail["steps"]]})
    assert res.status_code == 200, res.text


def test_the_sources_licence_note_is_kept_on_its_entries_and_in_exports(client, manager, web, monkeypatch):
    ScriptedModel(leave_drafts).install(monkeypatch)
    res = client.post("/api/kb/sources", headers=manager, json={
        "name": "Odoo-style docs", "url": URL, "public_confirmed": True, "licence_note": "CC BY-SA 4.0, Example S.A."})
    source_id = res.json()["source_id"]
    _run(client, manager, source_id)
    [source] = client.get("/api/kb/sources", headers=manager).json()["sources"]
    assert source["licence_note"] == "CC BY-SA 4.0, Example S.A."
    [row] = client.get("/api/kb/entries", headers=manager).json()["entries"]
    detail = client.get(f"/api/kb/entries/{row['kb_entry_id']}", headers=manager).json()
    assert detail["source_licence"] == "CC BY-SA 4.0, Example S.A." and detail["source_url"] == URL
    assert detail["source"]["licence_note"] == "CC BY-SA 4.0, Example S.A."
    client.post(f"/api/kb/entries/{row['kb_entry_id']}/approve", headers=manager, json={"version": detail["version"]})
    conn = db.get_connection()
    try:
        [exported] = kb_store.export_pack(conn)["entries"]
    finally:
        conn.close()
    assert exported["source_licence"] == "CC BY-SA 4.0, Example S.A." and exported["source_url"] == URL


def test_a_long_licence_note_is_refused(client, manager):
    res = client.post("/api/kb/sources", headers=manager, json={
        "name": "x", "url": URL, "public_confirmed": True, "licence_note": "x" * 201})
    assert res.status_code == 422
