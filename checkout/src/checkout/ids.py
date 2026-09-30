# SPDX-License-Identifier: AGPL-3.0-or-later
import re
import secrets


def new_quote_id() -> str:
    """Lowercase and dash-separated: valid as a Paystack transaction reference."""
    return f"qt-{secrets.token_hex(10)}"


def transaction_reference(quote_id: str, attempt: int) -> str:
    return f"{quote_id}-a{attempt}"


def transfer_reference(quote_id: str) -> str:
    return f"trf-{quote_id}"


_REFERENCE = re.compile(r"(?P<quote>qt-[0-9a-f]{20})-a\d+")


def quote_id_of(reference: str) -> str | None:
    """The quote a Paystack reference was made for, or None for a reference this server did not make."""
    found = _REFERENCE.fullmatch(reference)
    return found["quote"] if found else None
