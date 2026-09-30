# SPDX-License-Identifier: AGPL-3.0-or-later
"""What may enter a chat: a bounded message that holds no card number. Every way in (the page, a card,
an A2A caller) is checked here before anything is stored or sent to a model."""

import re
from typing import Any

MAX_CHARS = 500
_DIGIT_RUN = re.compile(r"\d(?:[ -]?\d){12,18}")
_ALNUM = re.compile(r"[A-Za-z0-9]")

# Card networks by leading digits and length: both must match, which keeps timestamps, phone numbers
# and long ids from being taken for a card.
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


class InputRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
        if stands_alone and _looks_like_card(re.sub(r"\D", "", match.group())):
            return True
    return False


def redact_card_numbers(text: str, replacement: str) -> str:
    """The text with each card number in it (a run that stands alone and passes the brand and Luhn checks)
    replaced."""

    def replace(match: re.Match[str]) -> str:
        before = text[match.start() - 1] if match.start() > 0 else ""
        after = text[match.end()] if match.end() < len(text) else ""
        alone = not _ALNUM.match(before or " ") and not _ALNUM.match(after or " ")
        return replacement if alone and _looks_like_card(re.sub(r"\D", "", match.group())) else match.group()

    return _DIGIT_RUN.sub(replace, text)


def clean_text(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise InputRefused("empty", "There is no message.")
    if len(text) > MAX_CHARS:
        raise InputRefused("too_long", f"A message can be up to {MAX_CHARS} characters.")
    if contains_card_number(text):
        raise InputRefused(
            "card_data",
            "That looks like a card number. Card details are never accepted here; "
            "payment happens on Paystack's own checkout page.",
        )
    return text
