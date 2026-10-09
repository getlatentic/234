# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cuts a source's text into passages that can be quoted: each is a slice of the text at known offsets, so
`text[start:end]` is the passage and the passages together lose and repeat nothing.

It cuts at a blank line when it can, then at the end of a sentence, then at a space, and only at the limit
when a word is longer than the limit."""

import re
from dataclasses import dataclass

LIMIT = 700
_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Passage:
    start: int
    end: int
    text: str


def _cut(text: str, start: int, limit: int) -> int:
    """Where the passage that begins at `start` ends."""
    end = min(start + limit, len(text))
    if end == len(text):
        return end
    window = text[start:end]
    for pattern in (_PARAGRAPH, _SENTENCE):
        stops = [m.end() for m in pattern.finditer(window)]
        if stops and stops[-1] > limit // 3:
            return start + stops[-1]
    space = window.rfind(" ")
    return start + space + 1 if space > limit // 3 else end


def chunk(text: str, limit: int = LIMIT) -> list[Passage]:
    passages: list[Passage] = []
    start = 0
    while start < len(text):
        end = _cut(text, start, limit)
        piece = text[start:end]
        if piece.strip():
            passages.append(Passage(start, end, piece))
        start = end
    return passages
