"""Uploaded files (TXT, MD, PDF) and pasted text as KB sources: the same
confirmation, estimate, caps and review as a web page (kb_ingester/files.py,
/api/kb/sources/upload|text). PDFs are made by tests/pdf_maker.py."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import db, main
from kb_ingester import files
from tests.kb_ingest_helpers import ScriptedModel
from tests.pdf_maker import make_pdf
from tests.test_kb_ingest_api import _login

GUIDE_LINES = ["Leave Guide", "Brightdesk lets employees request leave online.", "Apply for Leave",
               "Your manager approves each request.", "1. Open the Leave module.", "2. Click Apply Leave.",
               "3. Pick the dates and click Submit."]
MARKDOWN = "# Leave guide\n\nYour manager approves each request.\n\n## Apply\n\n1. Open Leave.\n2. Click Apply Leave.\n"


def _drafts(chunk):
    from kb_ingester.steps import ordered_lists

    lists = ordered_lists(chunk or "")
    entry = {"title": "Apply for leave", "kind": "how-to", "category": "USAGE",
             "questions": ["book a day off?", "the Apply button is greyed out", "How can I ask for leave?"],
             "answer": "Your manager approves the request after you send it."}
    if lists:
        entry.update(procedure=1, steps=[{"text": f"Do step {i}."} for i in range(1, len(lists[0]) + 1)])
    else:
        entry.update(kind="troubleshooting", steps=[])
    return {"entries": [entry], "proposed_terms": []}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def manager(client):
    return _login(client, "manager")


@pytest.fixture()
def model(monkeypatch):
    return ScriptedModel(_drafts).install(monkeypatch)


def _upload(client, headers, filename, data, *, name="Leave guide", confirmed=True, licence=""):
    return client.post("/api/kb/sources/upload", headers=headers,
                       data={"name": name, "public_confirmed": "true" if confirmed else "false",
                             "licence_note": licence},
                       files={"file": (filename, data)})


def _start(client, headers, run):
    res = client.post(f"/api/kb/runs/{run['run_id']}/start", headers=headers,
                      json={"expected_model_calls": run["estimated_model_calls"]})
    assert res.status_code == 200, res.text
    return client.get(f"/api/kb/runs/{run['run_id']}", headers=headers).json()


@pytest.mark.parametrize("filename, data", [
    ("guide.pdf", make_pdf([GUIDE_LINES])),
    ("guide.md", MARKDOWN.encode()),
    ("guide.txt", MARKDOWN.encode("utf-8-sig")),
])
def test_an_uploaded_file_is_estimated_drafted_and_reviewed_like_a_page(client, manager, model, filename, data):
    res = _upload(client, manager, filename, data, licence="Internal guide, used with permission")
    assert res.status_code == 201, res.text
    run = res.json()["run"]
    assert run["status"] == "estimated" and run["estimate"]["chunks_to_draft"] == 1 and model.calls == []
    run = _start(client, manager, run)
    assert run["status"] == "done" and run["drafts_created"] == 1
    [source] = client.get("/api/kb/sources", headers=manager).json()["sources"]
    assert source["kind"] == "file" and source["root_url"] is None and source["config"]["filename"] == filename
    [row] = client.get("/api/kb/entries", headers=manager).json()["entries"]
    detail = client.get(f"/api/kb/entries/{row['kb_entry_id']}", headers=manager).json()
    assert detail["source"]["kind"] == "file" and detail["source"]["filename"] == filename
    assert detail["source_url"] is None and detail["source_licence"] == "Internal guide, used with permission"
    assert [s["quote"] for s in detail["steps"]][0].startswith("Open")


def test_a_pdf_keeps_its_headings_and_numbered_steps(client, manager, model):
    pdf = make_pdf([GUIDE_LINES, ["Cancel a Request", "You can cancel a pending request from My Leave."]])
    run = _upload(client, manager, "guide.pdf", pdf).json()["run"]
    assert run["estimate"]["chunks"] == 1  # three short sections, merged
    _start(client, manager, run)
    draft = model.calls[0]["user"]
    assert "## Apply for Leave" in draft and "Procedure 1 (3 steps)" in draft


def test_a_scanned_pdf_is_reported_not_silently_empty(client, manager, model):
    res = _upload(client, manager, "scan.pdf", make_pdf([[], []]))
    assert res.status_code == 201
    run = res.json()["run"]
    assert (run["status"], run["stop_reason"], run["errors"]) == ("failed", "pdf_no_text", {"pdf_no_text": 1})
    assert run["estimated_model_calls"] == 0 and model.calls == []


def test_a_damaged_pdf_is_reported(client, manager, model):
    run = _upload(client, manager, "broken.pdf", b"%PDF-1.4\nnot really a pdf").json()["run"]
    assert (run["status"], run["stop_reason"]) == ("failed", "pdf_unreadable")


@pytest.mark.parametrize("filename, data, status, detail", [
    ("guide.docx", b"PK\x03\x04", 400, "Upload a .txt, .md or .pdf file"),
    ("guide.pdf", b"just text", 400, "This file isn't a PDF"),
    ("guide.txt", b"\xff\xfe\x00b\x00a\x00d", 400, "This file isn't UTF-8 text"),
    ("guide.txt", b"   \n", 400, "The file or text is empty"),
])
def test_bad_files_are_refused_before_a_source_is_made(client, manager, filename, data, status, detail):
    res = _upload(client, manager, filename, data)
    assert (res.status_code, res.json()["detail"]) == (status, detail)
    assert client.get("/api/kb/sources", headers=manager).json()["sources"] == []


def test_a_file_over_10_mb_is_refused(client, manager):
    res = _upload(client, manager, "big.txt", b"a" * (files.MAX_FILE_BYTES + 1))
    assert res.status_code == 413


def test_an_upload_request_over_the_limit_is_refused_before_it_is_read(client, manager):
    res = client.post("/api/kb/sources/upload", headers={**manager, "Content-Length": str(12 * 1024 * 1024)},
                      content=b"x")
    assert res.status_code == 413


def test_the_public_confirmation_is_required(client, manager):
    res = _upload(client, manager, "guide.md", MARKDOWN.encode(), confirmed=False)
    assert res.status_code == 400 and "public" in res.json()["detail"]


def test_a_file_source_runs_again_only_with_a_new_upload(client, manager, model):
    source_id = _upload(client, manager, "guide.md", MARKDOWN.encode()).json()["source_id"]
    res = client.post(f"/api/kb/sources/{source_id}/estimate", headers=manager)
    assert res.status_code == 400 and "isn't kept" in res.json()["detail"]
    res = client.post(f"/api/kb/sources/{source_id}/upload", headers=manager,
                      files={"file": ("guide-v2.md", MARKDOWN.encode())})
    assert res.status_code == 200 and res.json()["status"] == "estimated"


def test_pasted_text_is_a_source_and_an_unchanged_paste_costs_nothing(client, manager, model):
    res = client.post("/api/kb/sources/text", headers=manager,
                      json={"name": "Pasted FAQ", "text": MARKDOWN, "public_confirmed": True})
    assert res.status_code == 201, res.text
    source_id, run = res.json()["source_id"], res.json()["run"]
    _start(client, manager, run)
    again = client.post(f"/api/kb/sources/{source_id}/text", headers=manager, json={"text": MARKDOWN}).json()
    assert (again["status"], again["stop_reason"], again["estimated_model_calls"]) == ("done", "nothing_to_draft", 0)
    changed = client.post(f"/api/kb/sources/{source_id}/text", headers=manager,
                          json={"text": MARKDOWN.replace("Open Leave", "Open the Leave app")}).json()
    assert changed["status"] == "estimated" and changed["estimate"]["chunks_to_draft"] == 1
    [source] = client.get("/api/kb/sources", headers=manager).json()["sources"]
    assert source["kind"] == "text" and source["root_url"] is None


def test_pasted_text_is_limited_to_200k_characters(client, manager):
    res = client.post("/api/kb/sources/text", headers=manager,
                      json={"name": "Big", "text": "a" * (files.MAX_TEXT_CHARS + 1), "public_confirmed": True})
    assert res.status_code == 422
    res = client.post("/api/kb/sources/text", headers=manager, json={"name": "Empty", "text": " ", "public_confirmed": True})
    assert res.status_code == 400


def test_a_web_page_source_takes_no_upload(client, manager):
    source_id = client.post("/api/kb/sources", headers=manager, json={
        "name": "Page", "url": "https://help.example.com/x", "public_confirmed": True}).json()["source_id"]
    res = client.post(f"/api/kb/sources/{source_id}/upload", headers=manager, files={"file": ("a.md", b"# A")})
    assert res.status_code == 400


@pytest.mark.parametrize("role", ["technician", "admin"])
def test_only_managers_add_files_or_text(client, role):
    headers = _login(client, role)
    assert _upload(client, headers, "guide.md", MARKDOWN.encode()).status_code == 403
    res = client.post("/api/kb/sources/text", headers=headers,
                      json={"name": "x", "text": "hello", "public_confirmed": True})
    assert res.status_code == 403


@pytest.mark.parametrize("name, safe", [("../../etc/passwd.txt", "passwd.txt"), ("C:\\docs\\a b.md", "a b.md"),
                                        ("x<script>.md", "x_script_.md"), ("", "upload")])
def test_file_names_are_reduced_to_a_safe_base_name(name, safe):
    assert files.safe_filename(name) == safe


def test_pdf_heading_detection():
    text = files.mark_headings("Apply for Leave\nYou can apply.\nPage 3 of 9\n2.1 Approvals\nManagers approve.\n"
                               "Name\nDates\n1. Open Leave.")
    assert "## Apply for Leave" in text and "### 2.1 Approvals" in text
    assert "## Page 3 of 9" not in text and "## Name" not in text and "1. Open Leave." in text
