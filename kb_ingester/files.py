"""Uploaded files and pasted text as sources.

A file source (TXT, MD or PDF, at most MAX_FILE_BYTES) or a pasted-text
source (at most MAX_TEXT_CHARS) goes through the same estimate, caps and
review as a web page. The content is never stored: it is chunked at
estimate time (chunk text is purged after review, as for pages) and only
its hash is kept, so a new run needs the file uploaded (or the text
pasted) again; an unchanged version costs nothing. Each source has one
document (DOCUMENT_LOCATION), so a new version is compared with the last
one whatever the file is called, and entries from removed sections go
stale.

PDF: text is extracted page by page with pypdf (no OCR). A PDF with no
extractable text (a scan) is refused with the reason "pdf_no_text", shown
to the reviewer on the run, instead of producing nothing silently. Lines
that look like headings (short, no closing punctuation, title case or
capitals, or numbered "2.1 Setup") become "##" headings for the chunker.
"""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Iterator
from pathlib import PurePosixPath, PureWindowsPath

from backend.timeutil import utcnow
from kb_ingester.clean import CleanDocument
from kb_ingester.sources import RawDocument

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
MAX_PDF_PAGES = 500
# Fewer extracted characters than this per page (and in all): a scan.
MIN_CHARS_PER_PAGE = 20
TYPES = {".txt": "text/plain", ".md": "text/markdown", ".markdown": "text/markdown", ".pdf": "application/pdf"}
DOCUMENT_LOCATION = {"file": "uploaded file", "text": "pasted text"}

logging.getLogger("pypdf").setLevel(logging.ERROR)


class DocumentProblem(Exception):
    """`code`: unsupported_type, too_large, empty, not_text, pdf_unreadable,
    pdf_encrypted, pdf_too_many_pages, pdf_no_text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def safe_filename(name: str | None) -> str:
    base = PureWindowsPath(PurePosixPath(name or "").name).name
    base = re.sub(r"[^\w .()-]", "_", base).strip(" .")[:120]
    return base or "upload"


def _now() -> str:
    return utcnow().isoformat()


def file_document(filename: str, data: bytes) -> RawDocument:
    """Checks an upload's type, size and content. Raises DocumentProblem."""
    name = safe_filename(filename)
    content_type = TYPES.get(PurePosixPath(name.lower()).suffix)
    if content_type is None:
        raise DocumentProblem("unsupported_type")
    if len(data) > MAX_FILE_BYTES:
        raise DocumentProblem("too_large")
    if not data.strip():
        raise DocumentProblem("empty")
    if content_type == "application/pdf":
        if not data.lstrip()[:5] == b"%PDF-":
            raise DocumentProblem("not_pdf")
        charset = None
    else:
        if b"\x00" in data:
            raise DocumentProblem("not_text")
        try:
            data.decode("utf-8-sig")
            charset = "utf-8-sig"
        except UnicodeDecodeError:
            raise DocumentProblem("not_text") from None
    return RawDocument(location=DOCUMENT_LOCATION["file"], url=None, body=data, content_type=content_type,
                       charset=charset, fetched_at=_now())


def text_document(text: str) -> RawDocument:
    text = (text or "").replace("\r\n", "\n")
    if not text.strip():
        raise DocumentProblem("empty")
    if len(text) > MAX_TEXT_CHARS:
        raise DocumentProblem("too_large")
    return RawDocument(location=DOCUMENT_LOCATION["text"], url=None, body=text.encode("utf-8"),
                       content_type="text/markdown", charset="utf-8", fetched_at=_now())


class FileSource:
    kind = "file"

    def __init__(self, filename: str, data: bytes):
        self.document = file_document(filename, data)

    def documents(self) -> Iterator[RawDocument]:
        yield self.document


class TextSource:
    kind = "text"

    def __init__(self, text: str):
        self.document = text_document(text)

    def documents(self) -> Iterator[RawDocument]:
        yield self.document


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
# "2 Setup" / "2.1 Setup" (a number without a closing dot); "1. Open" is a list item.
_NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\s+\S")
_LIST_ITEM = re.compile(r"^(?:[-*\u2022\u25aa\u25e6]|\d+[.)])\s")
_PAGE_FOOTER = re.compile(r"^(?:page\s+)?\d+(?:\s*(?:of|/)\s*\d+)?$", re.IGNORECASE)
_SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with"}


def _heading_level(line: str) -> int | None:
    """2 or 3 when `line` looks like a heading, else None: short, no
    closing punctuation, and numbered ("2.1 Setup"), in capitals, or in
    title case."""
    text = line.strip()
    if not 3 <= len(text) <= 80 or text[-1] in ".,;:!?" or _PAGE_FOOTER.match(text):
        return None
    numbered = _NUMBERED_HEADING.match(text)
    if numbered:
        return 3 if "." in numbered.group(1) else 2
    if _LIST_ITEM.match(text):
        return None
    words = re.findall(r"[A-Za-z][\w'-]*", text)
    if not words or len(words) > 10:
        return None
    if text.upper() == text:
        return 2
    if words[0][0].isupper() and all(w[0].isupper() or w.lower() in _SMALL_WORDS for w in words):
        return 2
    return None


def mark_headings(page_text: str) -> str:
    """Heading-looking lines become "## ..."; the rest is kept as is.
    A line followed directly by another heading-looking line is left alone
    (a column of labels, not a heading)."""
    lines = [line.rstrip() for line in page_text.splitlines()]
    out = []
    for i, line in enumerate(lines):
        level = _heading_level(line)
        following = next((n for n in lines[i + 1:] if n.strip()), "")
        if level and following and _heading_level(following) is None:
            out += ["", "#" * level + " " + line.strip(), ""]
        else:
            out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def pdf_to_text(body: bytes) -> CleanDocument:
    """Raises DocumentProblem for an unreadable, locked, too long or
    scanned (no text) PDF."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(body), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentProblem("pdf_encrypted")
        pages = reader.pages
        if len(pages) > MAX_PDF_PAGES:
            raise DocumentProblem("pdf_too_many_pages")
        texts = [(page.extract_text() or "") for page in pages]
        title = ((reader.metadata or {}).get("/Title") or "") if reader.metadata else ""
    except DocumentProblem:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, AttributeError, IndexError, NotImplementedError):
        raise DocumentProblem("pdf_unreadable") from None
    except Exception:  # noqa: BLE001 — pypdf raises many kinds on a damaged file
        raise DocumentProblem("pdf_unreadable") from None
    extracted = sum(len(t.strip()) for t in texts)
    if not texts or extracted < MIN_CHARS_PER_PAGE * len(texts):
        raise DocumentProblem("pdf_no_text")
    text = "\n\n".join(mark_headings(t) for t in texts if t.strip())
    first = re.search(r"^#{1,3} (.+)$", text, re.M)
    return CleanDocument(title=str(title).strip()[:200] or (first.group(1)[:200] if first else ""), text=text)
