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


# ---------------------------------------------------------------------------
# Lead-in quotes, term filter, reference sections, answers, questions
# ---------------------------------------------------------------------------
from backend.ai_service import AIError, AIFailure, provider  # noqa: E402
from backend.ai_service import draft_kb_entries as op  # noqa: E402
from kb_ingester import checks  # noqa: E402
from kb_ingester.drafting import Budget, draft_chunk  # noqa: E402
from kb_ingester.steps import is_reference  # noqa: E402
from tests.kb_ingest_helpers import block  # noqa: E402

VENV = """# Activate

Once you have created it, you may activate it.

On Windows, run:

tutorial-env\\Scripts\\activate

The prompt then shows the environment's name."""


def _entry(**extra):
    base = {"title": "Activate the environment", "kind": "how-to", "category": "SETUP",
            "questions": ["activate venv on windows?", "the prompt doesn't show my env name", "How do I activate it?"],
            "answer": "You activate it so python and pip use the environment's own packages.", "steps": []}
    return {**base, **extra}


def _run_chunk(monkeypatch, chunk, *replies, supported=None):
    queue = list(replies)
    model = ScriptedModel(lambda c: queue.pop(0) if len(queue) > 1 else queue[0], supported).install(monkeypatch)
    result = draft_chunk(chunk, heading_path="Activate", page_title="Venv", source_url=None, known_terms=[],
                         budget=Budget(10))
    return result, model


def test_a_quote_that_stops_at_a_lead_in_is_rejected(monkeypatch):
    lead = {"text": "On Windows, run the activate script.", "quote": "On Windows, run:"}
    full = {"text": "On Windows, run tutorial-env\\Scripts\\activate.",
            "quote": "On Windows, run:\n\ntutorial-env\\Scripts\\activate"}
    result, _ = _run_chunk(monkeypatch, VENV, {"entries": [_entry(steps=[lead, full])], "proposed_terms": []})
    assert [s["quote"] for s in result.entries[0]["steps"]] == [full["quote"]]
    assert result.dropped["quote_lead_in"] == 1


def test_a_lead_in_at_the_very_end_of_a_section_is_allowed():
    assert checks.lead_in_problem("then type:", "Open a terminal, then type:") is None


@pytest.mark.parametrize("label, code", [
    ("Dates", "term_field_label"), ("Time Off Type", "term_field_label"), ("requirements.txt", "term_file"),
    ("src/app", "term_file"), (".venv", "term_file"), ("URL query", "term_url"), ("new?name=", "term_url"),
    ("tutorial-env", "term_generic"), ("dashboard", "term_generic"), ("Settings", "term_generic"),
    ("Leave", None), ("Time Off", None), ("GitHub CLI", None), ("Android", None), ("Payroll", None),
])
def test_proposed_term_labels_are_filtered(label, code):
    chunk = "- Dates: Enter the dates.\n- Time Off Type: pick one.\nOpen Leave and Time Off on Android."
    assert checks.term_label_problem(label, chunk) == code


def test_filtered_terms_are_not_proposed(monkeypatch):
    terms = [{"label": "Dates", "kind": "module", "aliases": [], "evidence_quote": "Enter the dates that apply."},
             {"label": "Leave", "kind": "module", "aliases": [], "evidence_quote": "Open the Leave module first."}]
    chunk = "- Dates: Enter the dates that apply.\nOpen the Leave module first."
    result, _ = _run_chunk(monkeypatch, chunk, {"entries": [], "proposed_terms": terms})
    assert [t["label"] for t in result.terms] == ["Leave"] and result.dropped["term_field_label"] == 1


TABLE = """## Query parameters

You can pre-fill the form with a URL.

Parameter | Example | Values
name | new?name=x | any name
visibility | new?visibility=private | public, private
owner | new?owner=me | an account"""


def test_tables_and_parameter_lists_are_reference_sections():
    assert is_reference(TABLE)
    assert is_reference("Options:\n- `name` the name\n- `owner` the owner\n- `size` the size")
    assert is_reference("- name (string): the name\n- owner (string): who\n- private (bool): hide it")
    assert not is_reference("- Dates: Enter the dates.\n- Description: Say why.\n- Type: pick one.")
    assert not is_reference(VENV)


def test_a_reference_section_gets_one_non_how_to_entry_at_most(monkeypatch):
    how_to = _entry(title="Pre-fill the form", steps=[{"text": "Add name.", "quote": "name | new?name=x | any name"}])
    ref = _entry(title="URL parameters", kind="reference", answer="A link can preset the name, owner and visibility.",
                 steps=[{"text": "Use name.", "quote": "name | new?name=x | any name"}])
    reply = {"entries": [how_to, ref, {**ref, "title": "Second"}], "proposed_terms": []}
    result, model = _run_chunk(monkeypatch, TABLE, reply)
    assert "reference: this section is mostly a table" in block("section_type", model.calls[0]["user"])
    assert "this section is reference material" in model.calls[1]["correction"]  # one retry
    assert [e["title"] for e in result.entries] == ["URL parameters"] and result.entries[0]["steps"] == []
    assert (result.dropped["reference_howto"], result.dropped["reference_extra"], result.dropped["reference_steps"]) == \
        (1, 1, 1)


def test_a_vacuous_answer_is_sent_back_once_then_removed(monkeypatch):
    step = {"text": "Run the activate script.", "quote": "On Windows, run:\n\ntutorial-env\\Scripts\\activate"}
    vacuous = {"entries": [_entry(answer="Follow the steps provided to activate it.", steps=[step])], "proposed_terms": []}
    fixed = {"entries": [_entry(steps=[step])], "proposed_terms": []}
    result, model = _run_chunk(monkeypatch, VENV, vacuous, fixed)
    assert "only points at the steps" in model.calls[1]["correction"]
    assert result.entries[0]["answer"].startswith("You activate it")
    result, _ = _run_chunk(monkeypatch, VENV, vacuous)
    assert result.entries[0]["answer"] == "" and result.entries[0]["notes"]["removed"] == ["answer_vacuous"]


def test_questions_all_in_one_template_get_one_retry_then_the_draft_is_rejected(monkeypatch):
    step = {"text": "Run the activate script.", "quote": "On Windows, run:\n\ntutorial-env\\Scripts\\activate"}
    templated = _entry(steps=[step], questions=["How do I activate?", "How do I turn it on?", "How do I start it?"])
    result, model = _run_chunk(monkeypatch, VENV, {"entries": [templated], "proposed_terms": []})
    assert "questions all start the same way" in model.calls[1]["correction"]
    assert result.entries == [] and result.dropped["questions_one_template"] == 1
    assert op.one_template(["How do I a?", "how do i b", "How do I c?"])
    assert not op.one_template(["How do I a?", "book a day off?", "the button is grey"])


def test_the_prompt_has_customer_wording_examples(monkeypatch):
    _, model = _run_chunk(monkeypatch, VENV, {"entries": [], "proposed_terms": []})
    system = model.calls[0]["system"]
    assert "the Apply button is greyed out, what am I missing?" in system and "book a day off?" in system


# ---------------------------------------------------------------------------
# Nova Pro drafting with a Lite fallback
# ---------------------------------------------------------------------------
def test_drafting_defaults_to_nova_pro_and_the_step_check_to_lite(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    with backends.model_task("draft_kb_entries"):
        assert backends.BedrockBackend.model_id() == "apac.amazon.nova-pro-v1:0"
    with backends.model_task("check_step_support"):
        assert backends.BedrockBackend.model_id() == "apac.amazon.nova-lite-v1:0"


def _models_used(monkeypatch, fail_kind):
    used = []

    def fake(messages, **kwargs):
        model = backends.BedrockBackend.model_id()
        used.append(model)
        if "nova-pro" in model:
            raise AIError("unavailable", AIFailure(kind=fail_kind, operation="draft_kb_entries"))
        return json.dumps({"entries": [_entry(kind="troubleshooting")], "proposed_terms": []})

    monkeypatch.setattr(provider, "complete", fake)
    monkeypatch.setattr(provider, "provider_name", lambda: "bedrock")
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    return used


def test_a_failing_drafting_model_falls_back_to_lite_once(monkeypatch):
    used = _models_used(monkeypatch, "access_denied")
    budget = Budget(10)
    result = draft_chunk(VENV, heading_path="x", page_title="", source_url=None, known_terms=[], budget=budget)
    assert used == ["apac.amazon.nova-pro-v1:0", "apac.amazon.nova-lite-v1:0"]
    assert len(result.entries) == 1 and result.dropped["drafting_model_fallback"] == 1
    assert result.calls == 2 and budget.used == 2


def test_no_fallback_for_a_bad_reply_or_without_budget(monkeypatch):
    _models_used(monkeypatch, "parse_schema")
    with pytest.raises(AIError):
        draft_chunk(VENV, heading_path="x", page_title="", source_url=None, known_terms=[], budget=Budget(10))
    _models_used(monkeypatch, "throttling")
    with pytest.raises(AIError):
        draft_chunk(VENV, heading_path="x", page_title="", source_url=None, known_terms=[], budget=Budget(2))
