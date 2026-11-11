"""Fakes for the KB ingester tests: DNS, web servers and the model.

- FakeWeb: host -> addresses (DNS answers, a list per lookup to simulate
  rebinding) and (host, path) -> raw HTTP response. Its connect() hands
  SafeFetcher a fake socket that replays the response, and records which
  address every connection went to.
- ScriptedModel: replaces provider.complete. Drafting requests get
  `drafts` (a dict, or a function of the chunk text); step checks get a
  verdict per id from `supported(step, quote)`.
"""

from __future__ import annotations

import gzip
import io
import json
import re

from backend.ai_service import provider
from kb_ingester import runs
from kb_ingester.steps import ordered_lists
from kb_ingester.safe_fetch import FetchError, HostPacer, SafeFetcher

PUBLIC_IP = "93.184.216.34"


def http_response(body: bytes | str = b"", *, status: int = 200, content_type: str = "text/html; charset=utf-8",
                  headers: dict | None = None) -> bytes:
    body = body.encode() if isinstance(body, str) else body
    reason = {200: "OK", 301: "Moved", 302: "Found", 404: "Not Found", 500: "Server Error"}.get(status, "X")
    lines = [f"HTTP/1.1 {status} {reason}"]
    all_headers = {"Content-Type": content_type, "Content-Length": str(len(body)), **(headers or {})}
    lines += [f"{k}: {v}" for k, v in all_headers.items() if v is not None]
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


def redirect(location: str, status: int = 302) -> bytes:
    return http_response(b"", status=status, headers={"Location": location})


def gzipped(body: bytes) -> bytes:
    return http_response(gzip.compress(body), headers={"Content-Encoding": "gzip"})


class FakeSocket:
    def __init__(self, response: bytes):
        self.response = response
        self.sent = b""

    def sendall(self, data):
        self.sent += data

    def makefile(self, mode="rb", *args, **kwargs):
        return io.BytesIO(self.response)

    def close(self):
        pass


class FakeWeb:
    def __init__(self):
        self.dns: dict[str, list] = {}
        self.pages: dict[tuple[str, str], bytes] = {}
        self.connections: list[tuple[str, int, str]] = []
        self.lookups: list[str] = []

    def host(self, name: str, *answers):
        """Each lookup takes the next answer (the last one repeats)."""
        self.dns[name] = [list(a) if isinstance(a, (list, tuple)) else [a] for a in (answers or [PUBLIC_IP])]
        return self

    def page(self, host: str, path: str, response: bytes):
        self.pages[(host, path)] = response
        return self

    def resolve(self, host, port):
        self.lookups.append(host)
        answers = self.dns.get(host)
        if not answers:
            raise FetchError("dns_failed")
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def connect(self, address, port, *, host, tls, timeout):
        self.connections.append((address, port, host))
        return _Recorder(self, host)

    def fetcher(self, **kwargs) -> SafeFetcher:
        kwargs.setdefault("min_interval", 0)
        return SafeFetcher(resolve=self.resolve, connect=self.connect, pacer=HostPacer(sleep=lambda s: None), **kwargs)


class _Recorder(FakeSocket):
    """Answers with the page for the request line it is sent."""

    def __init__(self, web: FakeWeb, host: str):
        super().__init__(b"")
        self.web, self.host = web, host

    def makefile(self, mode="rb", *args, **kwargs):
        match = re.match(rb"GET (\S+) HTTP", self.sent)
        path = match.group(1).decode() if match else "/"
        default = http_response(b"not found", status=404, content_type="text/plain")
        return io.BytesIO(self.web.pages.get((self.host, path), default))


def use_web(monkeypatch, web: FakeWeb) -> FakeWeb:
    monkeypatch.setattr(runs, "fetcher_factory", lambda: web.fetcher())
    return web


def block(name: str, content: str) -> str | None:
    match = re.search(rf"<{name}>\n(.*?)\n</{name}>", content, re.DOTALL)
    return match.group(1) if match else None


class ScriptedModel:
    def __init__(self, drafts=None, supported=None):
        self.drafts = drafts if drafts is not None else {"entries": [], "proposed_terms": []}
        self.supported = supported or (lambda step, quote: True)
        self.calls: list[dict] = []

    def __call__(self, messages, **kwargs):
        system, user = messages[0]["content"], messages[1]["content"]
        if "check draft help steps" in system:
            self.calls.append({"op": "check", "system": system, "user": user})
            steps = json.loads(block("steps_to_check", user))
            return json.dumps({"verdicts": [{"id": s["id"], "supported": bool(self.supported(s["step"], s["quote"]))}
                                            for s in steps]})
        self.calls.append({"op": "draft", "system": system, "user": user,
                           "correction": messages[2]["content"] if len(messages) > 2 else None})
        chunk = block("source_chunk", user)
        drafts = self.drafts(chunk) if callable(self.drafts) else self.drafts
        return json.dumps(drafts)

    def install(self, monkeypatch):
        monkeypatch.setattr(provider, "complete", self)
        return self

    def count(self, op: str) -> int:
        return sum(1 for c in self.calls if c["op"] == op)


LEAVE_PAGE = """<html><head><title>Apply for leave - Brightdesk Help</title></head><body>
<nav><a href="/">Home</a> <a href="/docs">Docs</a></nav>
<div class="cookie-banner">We use cookies. Accept all?</div>
<main><article>
<h1>Apply for leave</h1>
<p>Employees can request time off from the Leave module of the web app or the mobile app.
Your manager gets a notification and approves or declines the request.</p>
<h2>Steps</h2>
<ol>
<li>Open the Leave module from the left menu.</li>
<li>Click Apply Leave and choose the leave type.</li>
<li>Pick the start and end dates, then click Submit.</li>
</ol>
</article></main>
<footer>Copyright Brightdesk</footer>
<script>track()</script>
</body></html>"""


def confirm_terms(client, headers) -> None:
    """Confirm every proposed term: a drafted entry applies to the terms
    its own text names, and approving it needs them confirmed."""
    for term in client.get("/api/kb/terms", headers=headers).json()["terms"]:
        if term["status"] == "proposed":
            assert client.post(f"/api/kb/terms/{term['term_id']}/confirm", headers=headers).status_code == 200


def leave_drafts(chunk: str) -> dict:
    """The leave page's entry; its numbered list (as clean.py renders the
    page) is procedure 1, so the code takes the quotes from the items."""
    return {
        "entries": [{
            **({"procedure": 1} if ordered_lists(chunk or "") else {}),
            "title": "Apply for leave",
            "questions": ["How do I apply for leave?", "How can I request time off?", "Where do I ask for a day off?"],
            "answer": "You request time off in the Leave module; your manager then approves or declines it.",
            "kind": "how-to",
            "steps": [
                {"text": "Open Leave from the left menu.", "quote": "Open the Leave module from the left menu."},
                {"text": "Click Apply Leave and pick the leave type.",
                 "quote": "Click Apply Leave and choose the leave type."},
                {"text": "Choose the dates and submit.", "quote": "Pick the start and end dates, then click Submit."},
            ],
            "applies_to": [],
            "category": "USAGE",
        }],
        "proposed_terms": [{"label": "Leave", "kind": "module", "aliases": ["Leave module"],
                            "evidence_quote": "Open the Leave module from the left menu."}],
        "proposed_categories": [],
    }
