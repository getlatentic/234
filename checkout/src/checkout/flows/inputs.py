# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a quote is made from: text the model wrote and the amount it says the person said."""

import re

from ..amount.parse import parse_naira_amount
from ..errors import DomainError
from ..money import Kobo, format_naira

_REFERENCE = re.compile(r"[A-Za-z0-9._:/# -]{1,64}")
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9._:-]{8,64}")
_ACCOUNT_NUMBER = re.compile(r"\d{10}")


def clean_text(value: str, name: str, maximum: int) -> str:
    text = " ".join("".join(" " if ord(c) < 32 or ord(c) == 127 else c for c in value).split())
    if not text or len(text) > maximum:
        raise DomainError("INVALID_INPUT", f"{name} must be 1 to {maximum} characters.")
    return text


def clean_account(account_number: str) -> str:
    account = re.sub(r"[\s-]", "", account_number)
    if not _ACCOUNT_NUMBER.fullmatch(account):
        raise DomainError("INVALID_INPUT", "account_number must be a 10 digit Nigerian bank account number.")
    return account


def clean_reference(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not _REFERENCE.fullmatch(text):
        raise DomainError(
            "INVALID_INPUT", "merchant_ref must be 1 to 64 letters, digits or . _ : / # - characters."
        )
    return text


def assert_idempotency_key(key: str) -> None:
    if not _IDEMPOTENCY_KEY.fullmatch(key):
        raise DomainError(
            "INVALID_INPUT",
            "idempotency_key must be 8 to 64 characters: letters, digits, dot, dash, underscore or colon.",
        )


def confirm_stated_amount(amount_kobo: Kobo, as_user_said: str) -> None:
    """The amount the model passed must be the amount the user said; any doubt is refused."""
    if amount_kobo <= 0:
        raise DomainError("INVALID_INPUT", "amount_kobo must be a positive whole number of kobo.")
    read = parse_naira_amount(as_user_said)
    if read.kobo is None:
        raise DomainError(
            "AMOUNT_UNCLEAR",
            f'The user\'s amount "{as_user_said}" could not be confirmed: {read.message} '
            "Ask the user to say the amount again, then pass their exact words.",
        )
    if read.kobo != amount_kobo:
        raise DomainError(
            "AMOUNT_MISMATCH",
            f'The user\'s words "{as_user_said}" mean {format_naira(read.kobo)}, but amount_kobo was '
            f"{format_naira(amount_kobo)}. Nothing was quoted. Check with the user.",
        )
