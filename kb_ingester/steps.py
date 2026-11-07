"""Numbered procedures in a section, read by code (not the model).

clean.py renders an ordered list as consecutive "N. text" lines, nested
list lines indented under their item. A procedure is a run of two or more
such lines numbered consecutively; each item's text (with its nested lines)
is the quote for exactly one step. drafting.py hands them to the model,
which only rewrites each item in its own words, one for one, and checks
the count and order of what comes back.
"""

from __future__ import annotations

import re

_ITEM = re.compile(r"^(\d{1,3})\. (\S.*)$")
_NESTED = re.compile(r"^\s+(?:[-+*]|\d{1,3}\.) \S")


def ordered_lists(text: str) -> list[list[str]]:
    """Each numbered procedure in `text`, as its items' texts in order."""
    lists: list[list[str]] = []
    current: list[str] | None = None
    expected = 0
    for line in text.splitlines():
        match = _ITEM.match(line)
        if match:
            number, body = int(match.group(1)), match.group(2).strip()
            if current is not None and number == expected:
                current.append(body)
            else:
                current = [body]
                lists.append(current)
            expected = number + 1
        elif current is not None and _NESTED.match(line):
            current[-1] += "\n" + line.rstrip()
        elif current is not None and line.strip():
            current = None
    return [items for items in lists if len(items) >= 2]
