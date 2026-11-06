"""Cleaned text -> chunks: heading sections of about MIN_WORDS-MAX_WORDS.

The text is split at "#", "##" and "###" lines (clean.py renders h1-h3
that way). Each section keeps its heading path ("Leave > Apply"). A
section shorter than MIN_WORDS is merged with the ones after it (under
the first one's path) while the result stays under MAX_WORDS; a section
longer than MAX_WORDS is split at blank lines. At most MAX_CHUNKS chunks
per document; the rest are counted as capped.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MIN_WORDS = 300
MAX_WORDS = 1200
MAX_CHUNKS = 40

_HEADING = re.compile(r"^(#{1,3}) +(.+?) *#*$")


@dataclass
class Chunk:
    ordinal: int
    heading_path: str
    text: str
    start: int
    end: int

    @property
    def hash(self) -> str:
        return chunk_hash(self.heading_path, self.text)


def chunk_hash(heading_path: str, text: str) -> str:
    normal = " ".join(text.split())
    return hashlib.sha256(f"{heading_path}\n{normal}".encode()).hexdigest()


def content_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


def _words(text: str) -> int:
    return len(text.split())


def _sections(text: str) -> list[tuple[str, int, int]]:
    """(heading path, start, end) per heading section, in order."""
    sections, stack = [], []
    start, path, offset = 0, "", 0
    for line in text.splitlines(keepends=True):
        match = _HEADING.match(line.strip())
        if match:
            if offset > start:
                sections.append((path, start, offset))
            level = len(match.group(1))
            stack = [h for h in stack if h[0] < level] + [(level, match.group(2).strip())]
            path = " > ".join(h[1] for h in stack)
            start = offset
        offset += len(line)
    if offset > start:
        sections.append((path, start, offset))
    return [s for s in sections if text[s[1]:s[2]].strip()]


def _split_long(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """[start, end) cut at blank lines into pieces of at most MAX_WORDS
    (a single paragraph longer than that stays whole)."""
    pieces, piece_start, words = [], start, 0
    for match in re.finditer(r"(?:.+\n?)+|\n+", text[start:end]):
        para_words = _words(match.group(0))
        para_start = start + match.start()
        if words and words + para_words > MAX_WORDS:
            pieces.append((piece_start, para_start))
            piece_start, words = para_start, 0
        words += para_words
    pieces.append((piece_start, end))
    return [p for p in pieces if text[p[0]:p[1]].strip()]


def chunk_text(text: str) -> tuple[list[Chunk], int]:
    """(chunks, number left out over MAX_CHUNKS)."""
    merged: list[list] = []  # [path, start, end]
    for path, start, end in _sections(text):
        if merged:
            last = merged[-1]
            if (_words(text[last[1]:last[2]]) < MIN_WORDS
                    and _words(text[last[1]:end]) <= MAX_WORDS):
                last[2] = end
                continue
        merged.append([path, start, end])
    spans = [(path, a, b) for path, start, end in merged for a, b in _split_long(text, start, end)]
    chunks = [Chunk(ordinal=i, heading_path=path, text=text[a:b].strip(), start=a, end=b)
              for i, (path, a, b) in enumerate(spans[:MAX_CHUNKS], start=1)]
    return chunks, max(0, len(spans) - MAX_CHUNKS)
