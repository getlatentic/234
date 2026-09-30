# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reads a Nigerian amount phrase ("5k", "₦25,000", "2.5k naira") into kobo.

A phrase that can be read more than one way is rejected, never guessed. Amounts written as words
("two thousand", "five k", "wan tousand") are read by `words.parse_word_number`.
"""

import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction

from ..money import KOBO_PER_NAIRA, Kobo
from .words import parse_word_number

MAX_KOBO = 100_000_000_000  # ₦1 billion

_FOREIGN = re.compile(r"[$£€¢]|\b(usd|dollars?|gbp|pounds?|eur|euros?|ghs|cedis?|kes|shillings?|zar|rand)\b")
_HEDGES = re.compile(
    r"\b(or|to|between|maybe|perhaps|about|around|approx(?:imately)?|roughly|either|plus|minus"
    r"|minimum|maximum|atleast|almost|nearly)\b"
)
_RANGE_DASH = re.compile(r"\d\s*[-\u2013\u2014~/]\s*\d")
_FILLER = re.compile(r"\b(only|just|exactly|precisely)\b")
_NAIRA_WORDS = re.compile(r"₦|\bngn\b|\bnairas?\b")
_NAIRA_LETTER = re.compile(r"\bn(?=\s?\d)")
_DIGIT_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?|\.\d+")
_GROUPED = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_PLAIN = re.compile(r"^(?:\d+(?:\.\d+)?|\.\d+)$")
_ZERO_WIDTH = re.compile("[​-‍﻿]")

_SCALE = {
    "k": 1_000,
    "thousand": 1_000,
    "grand": 1_000,
    "m": 1_000_000,
    "mn": 1_000_000,
    "mil": 1_000_000,
    "million": 1_000_000,
    "hundred": 100,
}


@dataclass(frozen=True)
class AmountRead:
    kobo: Kobo | None
    reason: str | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.kobo is not None


def _reject(reason: str, message: str) -> AmountRead:
    return AmountRead(None, reason, message)


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", _ZERO_WIDTH.sub("", folded)).strip()


def _finish(kobo: int) -> AmountRead:
    if kobo <= 0:
        return _reject("not_positive", "The amount must be more than zero.")
    if kobo > MAX_KOBO:
        return _reject("too_large", "The amount is above ₦1,000,000,000.")
    return AmountRead(kobo)


def _digits_to_kobo(token: str, unit_word: str | None, in_kobo: bool) -> AmountRead:
    grouped = "," in token
    if not (_GROUPED if grouped else _PLAIN).match(token):
        return _reject(
            "ambiguous",
            f'"{token}" could be read more than one way. Use commas only for thousands, for example 25,000.',
        )
    digits = token.replace(",", "")
    fraction = digits.split(".")[1] if "." in digits else ""
    if unit_word is None and len(fraction) == 3:
        return _reject(
            "ambiguous",
            f'"{token}" could be a decimal or a thousands separator. '
            f"Write it as {digits.replace('.', ',')} or with two decimals.",
        )
    unit = _SCALE.get(unit_word, 1) if unit_word else 1
    kobo = Fraction(digits) * unit * (1 if in_kobo else KOBO_PER_NAIRA)
    if kobo.denominator != 1:
        return _reject("too_precise", "The amount has fractions of a kobo.")
    return _finish(int(kobo))


def _parse_digits(text: str, in_kobo: bool) -> AmountRead:
    tokens = _DIGIT_TOKEN.findall(text)
    if len(tokens) > 1:
        return _reject("ambiguous", f"More than one amount was given: {', '.join(tokens)}.")
    if not tokens:
        return _reject("unparseable", "No amount was found.")
    token = tokens[0]
    rest = re.sub(r"\s+", " ", text.replace(token, " ", 1)).strip()
    if rest and rest not in _SCALE:
        return _reject("unparseable", f'Could not read "{rest}" next to the number.')
    return _digits_to_kobo(token, rest or None, in_kobo)


def parse_naira_amount(phrase: str) -> AmountRead:
    text = _normalise(phrase)
    if not text:
        return _reject("empty", "No amount was given.")
    if _FOREIGN.search(text):
        return _reject("wrong_currency", "Only naira amounts are supported.")
    if _HEDGES.search(text) or _RANGE_DASH.search(text):
        return _reject("ambiguous", "The amount is a range or an estimate, not one exact figure.")
    in_kobo = bool(re.search(r"\bkobo\b", text))
    cleaned = text
    for pattern in (re.compile(r"\bkobo\b"), _NAIRA_WORDS, _NAIRA_LETTER, _FILLER):
        cleaned = pattern.sub(" ", cleaned)
    cleaned = _normalise(cleaned)
    if not cleaned:
        return _reject("empty", "No amount was given.")
    if re.search(r"\d", cleaned):
        return _parse_digits(cleaned, in_kobo)
    naira = parse_word_number(cleaned)
    if naira is None:
        return _reject("unparseable", "Could not read that as an amount.")
    return _finish(naira * KOBO_PER_NAIRA)
