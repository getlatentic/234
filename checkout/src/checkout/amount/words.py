# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whole naira from number words: "two thousand five hundred", "five k", "one million two hundred
thousand", and the Pidgin spellings people type ("wan tousand", "tu hundred"). A phrase that is not one
well-formed number is None, never a guess."""

import re

_SMALL = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}  # fmt: skip
_THOUSAND = frozenset({"thousand", "k", "grand"})
_MILLION = frozenset({"million", "mil", "m"})

# Pidgin as it is typed. Each spelling is one English number word, so a Pidgin phrase reads the same
# way as its English twin; words Pidgin shares with English are already covered above.
_PIDGIN = {
    "wan": "one", "tu": "two", "tri": "three", "fayv": "five", "fiv": "five", "sevin": "seven",
    "eit": "eight", "nain": "nine", "tousand": "thousand", "tausand": "thousand", "tosand": "thousand",
    "hundrid": "hundred", "hondred": "hundred", "milion": "million",
}  # fmt: skip

SCALES = ((_MILLION, 1_000_000), (_THOUSAND, 1_000))


class _Cursor:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self._index = 0

    def peek(self) -> str | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def next(self) -> str | None:
        token = self.peek()
        self._index += 1
        return token

    def skip(self, word: str) -> bool:
        if self.peek() != word:
            return False
        self._index += 1
        return True

    def done(self) -> bool:
        return self._index >= len(self._tokens)


def _read_tens_and_units(cursor: _Cursor) -> int | None:
    """1..99 from "seven", "twelve", "twenty", "twenty five"."""
    tens = _TENS.get(cursor.peek() or "")
    if tens is not None:
        cursor.next()
        unit = _SMALL.get(cursor.peek() or "")
        if unit is None or not 1 <= unit <= 9:
            return tens
        cursor.next()
        return tens + unit
    small = _SMALL.get(cursor.peek() or "")
    if small is None or small == 0:
        return None
    cursor.next()
    return small


def _read_hundreds_tail(cursor: _Cursor) -> int:
    cursor.skip("and")
    return _read_tens_and_units(cursor) or 0


def _read_group(cursor: _Cursor) -> int | None:
    """ "five", "five hundred", "two hundred and fifty", "fifteen hundred", "a hundred"."""
    article = cursor.peek() == "a"
    if article:
        cursor.next()
    if cursor.peek() == "hundred":
        cursor.next()
        return 100 + _read_hundreds_tail(cursor)
    scale_word = cursor.peek()
    if article and scale_word is not None and (scale_word in _THOUSAND or scale_word in _MILLION):
        return 1
    if article:
        return None
    lead = _read_tens_and_units(cursor)
    if lead is None:
        return None
    if not cursor.skip("hundred"):
        return lead
    return lead * 100 + _read_hundreds_tail(cursor)


def _read_scale(cursor: _Cursor, words: frozenset[str]) -> bool:
    word = cursor.peek()
    if word is None or word not in words:
        return False
    cursor.next()
    return True


def parse_word_number(text: str) -> int | None:
    tokens = [_PIDGIN.get(t, t) for t in re.split(r"[\s-]+", text) if t]
    cursor = _Cursor(tokens)
    pending = _read_group(cursor)
    total = 0
    for words, multiplier in SCALES:
        if pending is None:
            return None
        if not _read_scale(cursor, words):
            continue
        if pending >= 1000:
            return None
        total += pending * multiplier
        cursor.skip("and")
        pending = 0 if cursor.done() else _read_group(cursor)
    if pending is None or not cursor.done():
        return None
    return total + pending
