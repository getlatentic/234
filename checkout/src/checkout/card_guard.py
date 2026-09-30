# SPDX-License-Identifier: AGPL-3.0-or-later
"""Card details never travel through a tool, in either direction."""

import re
from typing import Any

from .errors import DomainError

_DIGIT_RUN = re.compile(r"\d(?:[ -]?\d){12,18}")
_ALNUM = re.compile(r"[A-Za-z0-9]")

# Card networks by leading digits and length. Both must match, which keeps timestamps, phone
# numbers and long numeric ids from being taken for a card.
_BRANDS: tuple[tuple[re.Pattern[str], tuple[int, ...]], ...] = (
    (re.compile(r"^4"), (13, 16, 19)),
    (re.compile(r"^(?:5[1-5]|2(?:2[2-9]|[3-6]\d|7[01]|720))"), (16,)),
    (re.compile(r"^3[47]"), (15,)),
    (re.compile(r"^(?:6011|64[4-9]|65)"), (16, 17, 18, 19)),
    (re.compile(r"^(?:506[01]|507[89]|6500)"), (16, 18, 19)),
    (re.compile(r"^35(?:2[89]|[3-8]\d)"), (16, 17, 18, 19)),
    (re.compile(r"^62"), (16, 17, 18, 19)),
    (re.compile(r"^(?:50|5[6-8]|6[0-9])"), (13, 14, 15, 16, 17, 18, 19)),
)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        n = int(char)
        if index % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _looks_like_card(digits: str) -> bool:
    branded = any(p.match(digits) and len(digits) in lengths for p, lengths in _BRANDS)
    return branded and _luhn_valid(digits)


def contains_card_number(text: str) -> bool:
    for match in _DIGIT_RUN.finditer(text):
        before = text[match.start() - 1] if match.start() > 0 else ""
        after = text[match.end()] if match.end() < len(text) else ""
        stands_alone = not _ALNUM.match(before or " ") and not _ALNUM.match(after or " ")
        digits = re.sub(r"\D", "", match.group())
        if stands_alone and _looks_like_card(digits):
            return True
    return False


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [s for item in value for s in _strings(item)]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    return []


def assert_no_card_data(value: Any, direction: str) -> None:
    if any(contains_card_number(s) for s in _strings(value)):
        raise DomainError(
            "CARD_DATA_REFUSED",
            "The input contains what looks like a card number. Card details are never accepted "
            "here; payment happens on Paystack's own checkout page."
            if direction == "input"
            else "The result contained what looks like a card number and was withheld.",
        )
