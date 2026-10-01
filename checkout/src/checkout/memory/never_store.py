# SPDX-License-Identifier: AGPL-3.0-or-later
"""What memory never keeps: card numbers, card security codes, PINs, one-time codes, passwords, API keys, and
long numbers that look like a BVN or a national ID. The check reads the title, the hook and the body together,
before a proposal is made and again before it is applied, and refuses with a reason the model can tell the
person.

A run of ten to thirteen digits is allowed only as a phone number in a preference or a fact whose title says
it is one. A recipient's account number is a field of its own and is not in any text."""

import re

from ..errors import DomainError

_SEPARATED_DIGITS = re.compile(r"\d(?:[ -]?\d)*")
_PHONE_TITLE = re.compile(
    r"phone|mobile|number|whatsapp|\bline\b|\bsim\b|airtime|\bdata\b|contact|call", re.I
)
_NIGERIAN_MOBILE = re.compile(r"(?:0|234)?[789][01]\d{8}")
_SECRET_WORDS = re.compile(
    r"\b(?:cvv2?|cvc2?|cid|pin|otp|password|passcode|passphrase|security code"
    r"|one[- ]time (?:code|password|pin)|secret (?:key|code|word)|private key|api[ _-]?key|access token"
    r"|bearer)\b",
    re.I,
)
_KEY_SHAPES = re.compile(r"\b(?:[sp]k_(?:test|live)_|AKIA[0-9A-Z]{8})|[A-Za-z0-9_-]{32,}")
_BVN_OR_NIN = re.compile(r"\b(?:bvn|nin)\b", re.I)
_LONGEST_NAME_RUN = 9
_CARD_LENGTHS = range(13, 20)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        n = int(char)
        if index % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _digit_runs(text: str) -> list[str]:
    return [re.sub(r"\D", "", run) for run in _SEPARATED_DIGITS.findall(text)]


def _is_card(digits: str) -> bool:
    return len(digits) in _CARD_LENGTHS and _luhn_valid(digits)


def _is_phone(digits: str, kind: str, title: str) -> bool:
    return (
        kind in ("preference", "fact")
        and bool(_PHONE_TITLE.search(title))
        and bool(_NIGERIAN_MOBILE.fullmatch(digits))
    )


def _number_problem(kind: str, title: str, text: str) -> str | None:
    for digits in _digit_runs(text):
        if _is_card(digits):
            return "That looks like a card number. 234 never keeps card numbers."
        if len(digits) > _LONGEST_NAME_RUN and not _is_phone(digits, kind, title):
            return (
                "That has a long number in it. 234 does not keep identity numbers such as a BVN or a NIN. "
                "A phone number is kept only in a preference or a fact whose title says it is a phone number."
            )
    return None


def _word_problem(text: str) -> str | None:
    if _SECRET_WORDS.search(text):
        return "That is about a PIN, a code, a password or a key. 234 never keeps those."
    if _BVN_OR_NIN.search(text):
        return "234 does not keep a BVN or a NIN."
    if _KEY_SHAPES.search(text):
        return "That looks like an API key or a secret. 234 never keeps those."
    return None


def refusal_reason(kind: str, title: str, hook: str, body: str) -> str | None:
    text = f"{title}\n{hook}\n{body}"
    return _number_problem(kind, title, text) or _word_problem(text)


def assert_storable(kind: str, title: str, hook: str, body: str) -> None:
    reason = refusal_reason(kind, title, hook, body)
    if reason is not None:
        raise DomainError("MEMORY_REFUSED", f"{reason} Nothing was saved. Tell the person why.")
