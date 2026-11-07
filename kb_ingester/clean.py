"""Page bytes -> plain text with "#" headings.

HTML: scripts, styles, forms, navigation, sidebars, cookie/consent
banners and share widgets go; the main content (<main>, role=main or
<article>, else <body>) is rendered block by block: h1-h3 as "#"/"##"/
"###" lines (what the chunker splits on), h4-h6 as plain lines, each
list item as ONE "- " or "1. " line (nested lists indented two spaces),
table rows as "a | b", <pre> kept as-is. Plain
text and Markdown pass through with their line breaks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

MAX_TEXT_CHARS = 300_000

_DROP_TAGS = ("script", "style", "noscript", "template", "nav", "aside", "form", "iframe", "svg",
              "canvas", "button", "select", "input", "textarea", "dialog", "object", "embed", "video",
              "audio", "picture", "map")
_NOISE_ROLES = {"navigation", "banner", "contentinfo", "complementary", "search", "dialog", "alertdialog"}
_NOISE_NAMES = re.compile(
    r"(^|[\s_-])(cookie|cookies|consent|gdpr|breadcrumbs?|sidebar|side-bar|navbar|topnav|share|sharing|"
    r"social|advert|ads|newsletter|subscribe|skip-link|toc|table-of-contents|feedback|was-this-helpful)"
    r"($|[\s_-])", re.IGNORECASE)
_BLOCKS = {"p", "div", "section", "article", "main", "blockquote", "dt", "dd", "figure", "figcaption",
           "details", "summary", "header", "footer", "address", "center", "body", "html", "hr"}
_SPACES = re.compile(r"[ \t\r\f\v\u00a0]+")
# Permalink anchors docs generators add to headings (Sphinx "\u00b6", "#", "\U0001f517").
_ANCHOR_CLASSES = re.compile(r"(^|[\s_-])(headerlink|anchor|anchorjs-link|heading-anchor|permalink)($|[\s_-])",
                             re.IGNORECASE)
_STRAY_COMMA = re.compile(r" ,(?=\s|$)")
_ANCHOR_TAIL = re.compile("[\\s\u00b6#\U0001f517]+$")


@dataclass
class CleanDocument:
    title: str
    text: str


def _is_noise(tag: Tag) -> bool:
    if tag.attrs is None or tag.name in ("html", "body", "main", "article"):
        return False
    if (tag.get("role") or "").lower() in _NOISE_ROLES:
        return True
    if tag.get("aria-hidden") == "true" or tag.has_attr("hidden"):
        return True
    names = " ".join([tag.get("id") or "", *(tag.get("class") or [])])
    return bool(names.strip()) and bool(_NOISE_NAMES.search(names))


def _one_line(node) -> str:
    """A block's text as one line (its paragraphs joined by a space)."""
    inner = _Renderer()
    inner.walk(node)
    inner.flush()
    return " ".join(line for line in inner.lines if line.strip())


class _Renderer:
    def __init__(self):
        self.lines: list[str] = []
        self.inline: list[str] = []

    def flush(self, prefix: str = "") -> None:
        text = _SPACES.sub(" ", "".join(self.inline)).strip()
        # An inline icon removed from "select <icon>, then" leaves a stray " ,".
        text = _STRAY_COMMA.sub(",", text)
        self.inline = []
        if text:
            self.lines.append(prefix + text)

    def blank(self) -> None:
        if self.lines and self.lines[-1] != "":
            self.lines.append("")

    def list_(self, tag: Tag, depth: int = 0) -> None:
        """Each item on ONE line ("1. ..." / "- ..."), nested lists after
        it indented two spaces per level, so a numbered procedure stays a
        run of "N. " lines (kb_ingester/steps.py reads them back)."""
        try:
            number = int(tag.get("start") or 1)
        except ValueError:
            number = 1
        for item in tag.find_all("li", recursive=False):
            nested = [sub for sub in item.find_all(["ul", "ol"]) if sub.find_parent("li") is item]
            for sub in nested:
                sub.extract()
            text = _one_line(item)
            if text:
                marker = f"{number}. " if tag.name == "ol" else "- "
                self.lines.append("  " * depth + marker + text)
                number += 1
            for sub in nested:
                self.list_(sub, depth + 1)

    def walk(self, node) -> None:
        for child in list(node.children):
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                self.inline.append(str(child).replace("\n", " "))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            if re.fullmatch(r"h[1-6]", name):
                self.flush()
                self.blank()
                level = int(name[1])
                self.inline.append(_ANCHOR_TAIL.sub("", child.get_text(" ")))
                self.flush("#" * level + " " if level <= 3 else "")
                self.blank()
            elif name in ("ul", "ol"):
                self.flush()
                self.blank()
                self.list_(child)
                self.blank()
            elif name == "pre":
                self.flush()
                self.blank()
                self.lines.extend(line.rstrip() for line in child.get_text().strip("\n").splitlines())
                self.blank()
            elif name == "table":
                self.flush()
                self.blank()
                for row in child.find_all("tr"):
                    cells = [_one_line(c) for c in row.find_all(["th", "td"])]
                    if any(cells):
                        self.lines.append(" | ".join(cells))
                self.blank()
            elif name == "br":
                self.flush()
            elif name in _BLOCKS:
                self.flush()
                self.walk(child)
                self.flush()
                self.blank()
            else:
                self.walk(child)


def html_to_text(body: bytes | str, charset: str | None = None) -> CleanDocument:
    soup = BeautifulSoup(body, "html.parser", from_encoding=charset if isinstance(body, bytes) else None)
    title = _SPACES.sub(" ", soup.title.get_text(" ")).strip()[:200] if soup.title else ""
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    for tag in soup.find_all(_is_noise):
        tag.decompose()
    for tag in soup.find_all("a", class_=_ANCHOR_CLASSES):
        tag.decompose()
    # Page headers and footers go, but an article's <header> holding its
    # title stays.
    for tag in soup.find_all(["header", "footer"]):
        if not tag.find(["h1", "h2"]):
            tag.decompose()
    root = (soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article")
            or soup.body or soup)
    renderer = _Renderer()
    renderer.walk(root)
    renderer.flush()
    text = "\n".join(renderer.lines).strip()
    if not title:
        first = re.search(r"^#{1,3} (.+)$", text, re.M)
        title = first.group(1)[:200] if first else ""
    return CleanDocument(title=title, text=text[:MAX_TEXT_CHARS])


def plain_to_text(body: bytes, charset: str | None = None) -> CleanDocument:
    text = body.decode(charset or "utf-8", "replace").replace("\r\n", "\n")
    lines = [_SPACES.sub(" ", line).rstrip() for line in text.splitlines()]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    first = re.search(r"^#{1,3} (.+)$", text, re.M)
    return CleanDocument(title=first.group(1)[:200] if first else "", text=text[:MAX_TEXT_CHARS])


def to_text(body: bytes, content_type: str, charset: str | None = None) -> CleanDocument:
    if content_type in ("text/html", "application/xhtml+xml"):
        return html_to_text(body, charset)
    return plain_to_text(body, charset)
