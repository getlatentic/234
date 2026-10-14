# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a delivered bill gives the buyer, read from a pay or requery reply: an electricity token with its
units and tariff, a Showmax voucher. A prepaid reply carries the token as `token` and as `purchased_code`
("Token : 2636..."); a postpaid one carries none, and then none is shown."""

import re
from typing import Any

_LABELLED_TOKEN = re.compile(r"^\s*token\s*:\s*(.+)$", re.I)
GROUP = 4


def _clean(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _grouped(token: str) -> str:
    digits = token.replace(" ", "").replace("-", "")
    if not digits.isdecimal():
        return token
    return " ".join(digits[i : i + GROUP] for i in range(0, len(digits), GROUP))


def _token(payload: dict[str, Any]) -> str | None:
    raw = _clean(payload.get("token")) or _clean(payload.get("purchased_code"))
    labelled = _LABELLED_TOKEN.match(raw) if raw else None
    if labelled:
        raw = labelled[1]
    elif not _clean(payload.get("token")):
        return None
    return _grouped(raw) if raw else None


def bill_receipt(payload: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """The lines a delivered bill adds to its receipt, in the order they read."""
    found = (
        ("Token", _token(payload)),
        ("Voucher", _clean(payload.get("Voucher"))),
        ("Units", _clean(payload.get("units"))),
        ("Tariff", _clean(payload.get("tariff"))),
    )
    return tuple((label, value) for label, value in found if value)
