"""SafeFetcher and UrlSource: what a source URL can and can't reach.

No network: DNS answers and servers are faked (tests/kb_ingest_helpers.py),
except a few URLs that must be refused before any lookup or connection.
"""

from __future__ import annotations

import gzip

import pytest

from kb_ingester import safe_fetch
from kb_ingester.safe_fetch import FetchError, HostPacer, SafeFetcher, address_problem, check_url
from kb_ingester.sources import RawDocument, SkippedDocument, UrlSource
from tests.kb_ingest_helpers import PUBLIC_IP, FakeWeb, gzipped, http_response, redirect

PAGE = http_response("<html><body><main><h1>Hello</h1><p>Some help text.</p></main></body></html>")


def _web(*answers, page=PAGE, host="help.example.com", path="/guide"):
    return FakeWeb().host(host, *answers).page(host, path, page)


def _code(fetcher, url):
    with pytest.raises(FetchError) as exc:
        fetcher.get(url)
    return exc.value.code


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("address", [
    "10.0.0.5", "172.16.3.4", "192.168.1.1", "127.0.0.1", "127.8.8.8", "0.0.0.0", "100.64.0.1",
    "169.254.10.10", "224.0.0.1", "240.0.0.1", "255.255.255.255", "192.0.2.10", "198.18.0.1",
    "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "ff02::1", "2001:db8::1",
    "::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "2002:7f00:1::1", "2001:0:4136:e378::1",
])
def test_private_and_special_addresses_are_refused(address):
    assert address_problem(address) == "private_address"


@pytest.mark.parametrize("address", ["169.254.169.254", "169.254.170.2", "fd00:ec2::254", "100.100.100.200"])
def test_cloud_metadata_addresses_are_refused(address):
    assert address_problem(address) == "metadata_address"


@pytest.mark.parametrize("address", [PUBLIC_IP, "8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8"])
def test_public_addresses_are_allowed(address):
    assert address_problem(address) is None


# ---------------------------------------------------------------------------
# URLs refused before any lookup
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("url, code", [
    ("file:///etc/passwd", "bad_scheme"),
    ("ftp://help.example.com/a", "bad_scheme"),
    ("gopher://help.example.com/", "bad_scheme"),
    ("javascript:alert(1)", "bad_scheme"),
    ("http://help.example.com:8080/", "bad_port"),
    ("https://help.example.com:22/", "bad_port"),
    ("http://help.example.com:443/", "bad_port"),
    ("http://user:pass@help.example.com/", "credentials_in_url"),
    ("http://localhost/", "private_address"),
    ("http://api.localhost/", "private_address"),
    ("http://db.internal/", "private_address"),
    ("http://printer.local/", "private_address"),
    ("http://", "bad_url"),
    ("http://help.example.com:99999/", "bad_url"),
    ("http://help.example.com/" + "a" * 3000, "bad_url"),
])
def test_bad_urls_are_refused_without_a_lookup(url, code):
    web = FakeWeb()
    assert _code(web.fetcher(), url) == code
    assert web.lookups == [] and web.connections == []


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.1/", "http://0x7f000001/", "http://2130706433/",
])
def test_private_literal_and_encoded_addresses_are_refused_by_the_real_resolver(url, monkeypatch):
    """The system resolver turns these into loopback/private/metadata
    addresses (or fails); nothing is ever connected to."""
    connected = []
    monkeypatch.setattr(safe_fetch, "system_connect", lambda *a, **k: connected.append(a))
    fetcher = SafeFetcher(min_interval=0, connect=lambda *a, **k: connected.append(a))
    assert _code(fetcher, url) in {"private_address", "metadata_address", "dns_failed"}
    assert connected == []


# ---------------------------------------------------------------------------
# DNS answers
# ---------------------------------------------------------------------------
def test_a_name_resolving_to_a_private_address_is_refused():
    web = _web("10.1.2.3")
    assert _code(web.fetcher(), "http://help.example.com/guide") == "private_address"
    assert web.connections == []


def test_a_mixed_answer_with_one_private_address_is_refused():
    web = _web([PUBLIC_IP, "127.0.0.1"])
    assert _code(web.fetcher(), "http://help.example.com/guide") == "private_address"
    assert web.connections == []


def test_a_name_resolving_to_the_metadata_address_is_refused():
    web = _web("169.254.169.254")
    assert _code(web.fetcher(), "http://help.example.com/guide") == "metadata_address"


def test_dns_rebinding_cant_swap_in_a_private_address():
    """The second lookup would answer 127.0.0.1. The fetcher looks up
    once per request and connects to the address it checked."""
    web = _web(PUBLIC_IP, "127.0.0.1")
    result = web.fetcher().get("http://help.example.com/guide")
    assert result.status == 200
    assert web.connections == [(PUBLIC_IP, 80, "help.example.com")]
    assert web.lookups == ["help.example.com"]


def test_rebinding_between_redirect_hops_is_caught():
    """Each hop is resolved and checked again: here the second lookup of
    the same host (after a redirect) answers a private address."""
    web = _web(PUBLIC_IP, "10.0.0.7").page("help.example.com", "/old", redirect("/guide"))
    assert _code(web.fetcher(), "http://help.example.com/old") == "private_address"
    assert web.connections == [(PUBLIC_IP, 80, "help.example.com")]


def test_the_request_names_the_host_and_https_is_verified_for_it():
    seen = {}
    web = _web()

    def connect(address, port, *, host, tls, timeout):
        seen.update(address=address, port=port, host=host, tls=tls)
        return web.connect(address, port, host=host, tls=tls, timeout=timeout)

    fetcher = SafeFetcher(resolve=web.resolve, connect=connect, min_interval=0)
    fetcher.get("https://help.example.com/guide")
    assert seen == {"address": PUBLIC_IP, "port": 443, "host": "help.example.com", "tls": True}


# ---------------------------------------------------------------------------
# Redirects
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("location, code", [
    ("http://10.0.0.5/admin", "private_address"),
    ("http://127.0.0.1:80/", "private_address"),
    ("http://[::1]/", "private_address"),
    ("http://169.254.169.254/latest/meta-data/iam/", "metadata_address"),
    ("http://internal.example.com/", "private_address"),
    ("file:///etc/passwd", "bad_scheme"),
    ("http://help.example.com:6379/", "bad_port"),
    ("http://localhost/", "private_address"),
])
def test_redirects_to_private_places_are_refused(location, code):
    web = _web().host("internal.example.com", "192.168.0.10").page(
        "help.example.com", "/start", redirect(location))
    assert _code(web.fetcher(), "http://help.example.com/start") == code
    assert all(c[0] == PUBLIC_IP for c in web.connections)


def test_a_public_redirect_is_followed_and_reported():
    web = _web().page("help.example.com", "/start", redirect("https://help.example.com/guide", 301))
    result = web.fetcher().get("http://help.example.com/start")
    assert result.url == "https://help.example.com/guide" and result.redirects == ["https://help.example.com/guide"]


def test_too_many_redirects():
    web = FakeWeb().host("help.example.com")
    for i in range(10):
        web.page("help.example.com", f"/r{i}", redirect(f"/r{i + 1}"))
    assert _code(web.fetcher(), "http://help.example.com/r0") == "too_many_redirects"
    assert len(web.connections) == safe_fetch.MAX_REDIRECTS + 1


# ---------------------------------------------------------------------------
# Size, type, time
# ---------------------------------------------------------------------------
def test_a_declared_length_over_the_cap_is_refused():
    web = _web(page=http_response(b"x" * 2000))
    assert _code(web.fetcher(max_bytes=1000), "http://help.example.com/guide") == "too_large"


def test_a_streamed_body_over_the_cap_is_refused_without_a_length():
    body = b"x" * 5000
    raw = http_response(body, headers={"Content-Length": None})
    web = _web(page=raw)
    assert _code(web.fetcher(max_bytes=1000), "http://help.example.com/guide") == "too_large"


def test_a_gzip_bomb_is_refused():
    web = _web(page=gzipped(b"a" * 5_000_000))
    assert _code(web.fetcher(max_bytes=100_000), "http://help.example.com/guide") == "too_large"


def test_a_small_gzip_page_is_decoded():
    web = _web(page=gzipped(b"<p>hello</p>"))
    assert web.fetcher().get("http://help.example.com/guide").body == b"<p>hello</p>"


@pytest.mark.parametrize("content_type", ["application/octet-stream", "image/png", "application/x-sh",
                                          "application/json", ""])
def test_other_content_types_are_refused(content_type):
    web = _web(page=http_response(b"data", content_type=content_type))
    assert _code(web.fetcher(), "http://help.example.com/guide") == "bad_content_type"


def test_http_errors_carry_the_status():
    web = _web(page=http_response(b"gone", status=404))
    with pytest.raises(FetchError) as exc:
        web.fetcher().get("http://help.example.com/guide")
    assert exc.value.code == "http_404" and exc.value.status == 404


def test_the_overall_deadline():
    ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0])
    web = _web()
    fetcher = SafeFetcher(resolve=web.resolve, connect=web.connect, min_interval=0, deadline=30,
                          clock=lambda: next(ticks))
    assert _code(fetcher, "http://help.example.com/guide") == "timeout"


def test_requests_to_one_host_are_paced():
    now, slept = [0.0], []
    pacer = HostPacer(clock=lambda: now[0], sleep=slept.append)
    pacer.wait("help.example.com", 1.0)
    pacer.wait("help.example.com", 1.0)
    pacer.wait("other.example.com", 1.0)
    now[0] = 5.0
    pacer.wait("help.example.com", 1.0)
    assert slept == [1.0]


def test_the_request_asks_for_no_compression_and_names_the_bot():
    web = _web()
    sockets = []

    def connect(*args, **kwargs):
        sock = web.connect(*args, **kwargs)
        sockets.append(sock)
        return sock

    SafeFetcher(resolve=web.resolve, connect=connect, min_interval=0).get("http://help.example.com/guide")
    request = sockets[0].sent.decode()
    assert "Accept-Encoding: identity" in request and safe_fetch.USER_AGENT in request
    assert "Host: help.example.com" in request


# ---------------------------------------------------------------------------
# UrlSource and robots.txt
# ---------------------------------------------------------------------------
def test_url_source_yields_the_page():
    web = _web()
    [doc] = UrlSource("http://help.example.com/guide", web.fetcher()).documents()
    assert isinstance(doc, RawDocument) and doc.location == doc.url == "http://help.example.com/guide"
    assert doc.content_type == "text/html" and b"Hello" in doc.body


def test_robots_txt_disallowing_the_bot_is_respected():
    web = _web().page("help.example.com", "/robots.txt",
                      http_response("User-agent: SahayakKBBot\nDisallow: /guide\n", content_type="text/plain"))
    [doc] = UrlSource("http://help.example.com/guide", web.fetcher()).documents()
    assert isinstance(doc, SkippedDocument) and doc.code == "robots_disallowed"
    assert all(c for c in web.connections)  # only robots.txt was read
    assert len(web.connections) == 1


def test_an_unreadable_robots_txt_allows_nothing():
    web = _web().page("help.example.com", "/robots.txt", http_response("oops", status=500, content_type="text/plain"))
    [doc] = UrlSource("http://help.example.com/guide", web.fetcher()).documents()
    assert isinstance(doc, SkippedDocument) and doc.code == "robots_disallowed"


def test_a_private_source_url_is_skipped_with_its_reason():
    web = FakeWeb().host("help.example.com", "10.0.0.1")
    [doc] = UrlSource("http://help.example.com/guide", web.fetcher()).documents()
    assert isinstance(doc, SkippedDocument) and doc.code == "private_address"


def test_check_url_keeps_the_query():
    assert check_url("https://Help.Example.com/a?b=1").path == "/a?b=1"
    assert check_url("https://Help.Example.com").host == "help.example.com"


def test_gzip_helper_is_real_gzip():
    assert gzip.decompress(gzipped(b"x").split(b"\r\n\r\n", 1)[1]) == b"x"
