"""Where documents come from.

A Source yields RawDocuments (or SkippedDocuments with a reason code).
The pipeline after it (clean, chunk, draft, store) doesn't care which
kind of source a document came from, so whole-site crawls, forum threads,
uploaded files, pasted text and resolved tickets slot in as more Source
classes. This slice has UrlSource: one page.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol
from urllib import robotparser
from urllib.parse import urlsplit, urlunsplit

from backend.timeutil import utcnow
from kb_ingester.safe_fetch import USER_AGENT, FetchError, SafeFetcher, check_url

ROBOTS_TYPES = frozenset({"text/plain", "text/html", "application/octet-stream"})
ROBOTS_MAX_BYTES = 512 * 1024


@dataclass
class RawDocument:
    location: str  # what the source names: the URL asked for, or a file name
    url: str | None  # where it was read from (after redirects); the entries' source link
    body: bytes
    content_type: str
    charset: str | None
    fetched_at: str
    etag: str | None = None
    last_modified: str | None = None


@dataclass
class SkippedDocument:
    location: str
    code: str  # robots_disallowed, private_address, http_404, ...
    status: int | None = None


class Source(Protocol):
    kind: str

    def documents(self) -> Iterator[RawDocument | SkippedDocument]: ...


def robots_allows(fetcher: SafeFetcher, url: str) -> bool:
    """robots.txt for the URL's host, fetched with the same safe fetcher.
    No robots.txt (any 4xx) allows everything; a server error allows
    nothing, as the robots standard says. A refused or failed connection
    raises its FetchError (the page would fail the same way)."""
    target = check_url(url)
    parts = urlsplit(url)
    robots_url = urlunsplit((target.scheme, parts.netloc, "/robots.txt", "", ""))
    try:
        result = fetcher.get(robots_url, allowed_types=ROBOTS_TYPES)
    except FetchError as exc:
        if exc.status is not None and 400 <= exc.status < 500:
            return True
        if exc.status is not None:
            return False
        raise
    parser = robotparser.RobotFileParser()
    parser.parse(result.body[:ROBOTS_MAX_BYTES].decode("utf-8", "replace").splitlines())
    return parser.can_fetch(USER_AGENT, url)


class UrlSource:
    kind = "url"

    def __init__(self, url: str, fetcher: SafeFetcher | None = None):
        self.url = url
        self.fetcher = fetcher or SafeFetcher()

    def documents(self) -> Iterator[RawDocument | SkippedDocument]:
        try:
            check_url(self.url)
            if not robots_allows(self.fetcher, self.url):
                yield SkippedDocument(self.url, "robots_disallowed")
                return
            result = self.fetcher.get(self.url)
        except FetchError as exc:
            yield SkippedDocument(self.url, exc.code, exc.status)
            return
        yield RawDocument(location=self.url, url=result.url, body=result.body, content_type=result.content_type,
                          charset=result.charset, fetched_at=utcnow().isoformat(), etag=result.etag,
                          last_modified=result.last_modified)
