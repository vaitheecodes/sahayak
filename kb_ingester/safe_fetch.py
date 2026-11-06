"""SafeFetcher: fetch a public web page without letting a URL reach
anything private (server-side request forgery).

- http and https only, ports 80 and 443, no user:password@ in the URL.
- The host name is resolved once and every address it resolves to must
  be public: private, loopback, link-local, CGNAT, multicast, reserved,
  documentation, IPv6 unique-local and cloud metadata addresses are
  refused (IPv4-mapped, 6to4 and NAT64 IPv6 addresses are checked as the
  IPv4 address inside them). The connection goes to the address that was
  checked, so a second DNS answer (DNS rebinding) can't swap in another;
  TLS still verifies the certificate against the host name.
- Redirects are followed by hand, at most MAX_REDIRECTS, and every hop is
  checked again from the start.
- Limits: a byte cap on the body (Content-Length and the streamed bytes,
  and again after gzip/deflate decoding), a per-socket timeout and an
  overall deadline, a content-type allowlist checked before the body is
  read, and per-host pacing (at least min_interval seconds between
  requests to one host, in this process).
- No proxy is ever used (http.client ignores *_proxy variables).

Failures raise FetchError with a short reason code; codes are what runs
record, never page text.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

USER_AGENT = "SahayakKBBot/1.0 (+knowledge base ingester)"
MAX_REDIRECTS = 5
MAX_URL_LENGTH = 2048
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 10.0
DEFAULT_DEADLINE = 30.0
DEFAULT_MIN_INTERVAL = 1.0
PAGE_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain", "text/markdown"})
ALLOWED_PORTS = {"http": 80, "https": 443}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# Cloud instance metadata services (AWS, ECS task, AWS IPv6, Alibaba,
# Oracle). All are also inside a blocked range; named for a clearer code.
METADATA_ADDRESSES = frozenset({
    ipaddress.ip_address(a) for a in
    ("169.254.169.254", "169.254.170.2", "fd00:ec2::254", "100.100.100.200", "192.0.0.192")
})
_BLOCKED_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
    "192.0.0.0/24", "192.0.2.0/24", "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
    "::/128", "::1/128", "100::/64", "2001::/23", "2001:db8::/32", "fc00::/7", "fe80::/10",
    "fec0::/10", "ff00::/8",
))
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa")


class FetchError(Exception):
    """`code` is a short reason (private_address, too_large, http_404 ...)."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass
class FetchResult:
    url: str
    status: int
    content_type: str
    charset: str | None
    body: bytes
    etag: str | None = None
    last_modified: str | None = None
    redirects: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Address and URL checks
# ---------------------------------------------------------------------------
def address_problem(address: str) -> str | None:
    """None for a public address; else metadata_address or private_address."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return "bad_address"
    if ip.version == 6:
        embedded = ip.ipv4_mapped or ip.sixtofour
        if embedded is None and ip in _NAT64:
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if embedded is not None:
            return address_problem(str(embedded))
        if ip.teredo:
            return "private_address"
    if ip in METADATA_ADDRESSES:
        return "metadata_address"
    if (any(ip in net for net in _BLOCKED_NETWORKS) or not ip.is_global or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified):
        return "private_address"
    return None


@dataclass(frozen=True)
class Target:
    scheme: str
    host: str
    port: int
    path: str  # path + query, never empty


def check_url(url: str) -> Target:
    """Syntax checks that need no network. Raises FetchError."""
    if not isinstance(url, str) or not url.strip() or len(url) > MAX_URL_LENGTH:
        raise FetchError("bad_url")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise FetchError("bad_url") from None
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_PORTS:
        raise FetchError("bad_scheme")
    if parts.username is not None or parts.password is not None:
        raise FetchError("credentials_in_url")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise FetchError("bad_url")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise FetchError("bad_url") from None
    if port is None:
        port = ALLOWED_PORTS[scheme]
    if port != ALLOWED_PORTS[scheme]:
        raise FetchError("bad_port")
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise FetchError("private_address")
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return Target(scheme, host, port, path)


def system_resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise FetchError("dns_failed") from None
    return list(dict.fromkeys(info[4][0] for info in infos))


def system_connect(address: str, port: int, *, host: str, tls: bool, timeout: float):
    """A socket to `address` (already checked); TLS verified for `host`."""
    try:
        sock = socket.create_connection((address, port), timeout=timeout)
    except socket.timeout:
        raise FetchError("timeout") from None
    except OSError:
        raise FetchError("connect_failed") from None
    if not tls:
        return sock
    try:
        return ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    except socket.timeout:
        sock.close()
        raise FetchError("timeout") from None
    except (ssl.SSLError, OSError):
        sock.close()
        raise FetchError("tls_error") from None


# ---------------------------------------------------------------------------
# Pacing
# ---------------------------------------------------------------------------
class HostPacer:
    """At least `interval` seconds between requests to one host."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self._clock, self._sleep = clock, sleep
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, interval: float) -> None:
        with self._lock:
            now = self._clock()
            start = max(now, self._next.get(host, 0.0))
            self._next[host] = start + interval
        if start > now:
            self._sleep(start - now)


PACER = HostPacer()


# ---------------------------------------------------------------------------
# The fetcher
# ---------------------------------------------------------------------------
def _content_type(value: str | None) -> tuple[str, str | None]:
    if not value:
        return "", None
    kind, _, params = value.partition(";")
    charset = None
    for param in params.split(";"):
        name, _, val = param.strip().partition("=")
        if name.lower() == "charset" and val:
            charset = val.strip().strip('"').lower()[:40]
    return kind.strip().lower(), charset


def _decode(body: bytes, encoding: str, max_bytes: int) -> bytes:
    encoding = (encoding or "identity").strip().lower()
    if encoding in ("", "identity"):
        return body
    if encoding not in ("gzip", "x-gzip", "deflate"):
        raise FetchError("bad_encoding")
    wbits = 16 + zlib.MAX_WBITS if "gzip" in encoding else zlib.MAX_WBITS
    try:
        inflater = zlib.decompressobj(wbits)
        out = inflater.decompress(body, max_bytes + 1)
    except zlib.error:
        raise FetchError("bad_encoding") from None
    if len(out) > max_bytes or inflater.unconsumed_tail:
        raise FetchError("too_large")
    return out


class SafeFetcher:
    """resolve(host, port) -> [addresses] and connect(address, port, host=,
    tls=, timeout=) -> socket are injectable (tests simulate DNS answers
    and servers without a network)."""

    def __init__(self, *, max_bytes: int = DEFAULT_MAX_BYTES, timeout: float = DEFAULT_TIMEOUT,
                 deadline: float = DEFAULT_DEADLINE, min_interval: float = DEFAULT_MIN_INTERVAL,
                 resolve=system_resolve, connect=system_connect, pacer: HostPacer | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.max_bytes, self.timeout, self.deadline = max_bytes, timeout, deadline
        self.min_interval = min_interval
        self._resolve, self._connect = resolve, connect
        self._pacer = pacer or PACER
        self._clock = clock

    def checked_address(self, target: Target) -> str:
        literal = target.host.strip("[]")
        try:
            addresses = [str(ipaddress.ip_address(literal))]
        except ValueError:
            addresses = self._resolve(target.host, target.port)
        if not addresses:
            raise FetchError("dns_failed")
        # Every answer must be public: a mixed answer is how rebinding
        # tricks pick the private one later.
        for address in addresses:
            problem = address_problem(address)
            if problem:
                raise FetchError(problem)
        return addresses[0]

    def get(self, url: str, *, allowed_types=PAGE_TYPES) -> FetchResult:
        """Raises FetchError (http_<status> for a 4xx/5xx answer)."""
        end = self._clock() + self.deadline
        redirects: list[str] = []
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            target = check_url(current)
            address = self.checked_address(target)
            self._pacer.wait(target.host, self.min_interval)
            status, headers, body = self._request(target, address, allowed_types, end)
            if status in REDIRECT_STATUSES:
                location = headers.get("location")
                if not location:
                    raise FetchError("bad_redirect", status)
                current = urljoin(current, location.strip())
                redirects.append(current)
                continue
            if status >= 400:
                raise FetchError(f"http_{status}", status)
            if status != 200:
                raise FetchError("unexpected_status", status)
            kind, charset = _content_type(headers.get("content-type"))
            return FetchResult(url=current, status=status, content_type=kind, charset=charset,
                               body=_decode(body, headers.get("content-encoding", ""), self.max_bytes),
                               etag=headers.get("etag"), last_modified=headers.get("last-modified"),
                               redirects=redirects)
        raise FetchError("too_many_redirects")

    def _request(self, target: Target, address: str, allowed_types, end: float):
        remaining = end - self._clock()
        if remaining <= 0:
            raise FetchError("timeout")
        sock = self._connect(address, target.port, host=target.host, tls=target.scheme == "https",
                             timeout=min(self.timeout, remaining))
        conn = http.client.HTTPConnection(target.host, target.port, timeout=self.timeout)
        conn.sock = sock  # already connected to the checked address
        try:
            conn.request("GET", target.path, headers={
                "User-Agent": USER_AGENT, "Accept": ", ".join(sorted(allowed_types)) + ";q=0.9, */*;q=0.1",
                "Accept-Encoding": "identity", "Connection": "close"})
            response = conn.getresponse()
            headers = {k.lower(): v for k, v in response.getheaders()}
            if response.status in REDIRECT_STATUSES or response.status >= 400:
                return response.status, headers, b""
            kind, _ = _content_type(headers.get("content-type"))
            if kind not in allowed_types:
                raise FetchError("bad_content_type", response.status)
            length = headers.get("content-length", "")
            if length.isdigit() and int(length) > self.max_bytes:
                raise FetchError("too_large", response.status)
            parts, size = [], 0
            while True:
                if self._clock() > end:
                    raise FetchError("timeout")
                block = response.read(65536)
                if not block:
                    break
                size += len(block)
                if size > self.max_bytes:
                    raise FetchError("too_large", response.status)
                parts.append(block)
            return response.status, headers, b"".join(parts)
        except socket.timeout:
            raise FetchError("timeout") from None
        except (http.client.HTTPException, OSError):
            raise FetchError("bad_response") from None
        finally:
            conn.close()
