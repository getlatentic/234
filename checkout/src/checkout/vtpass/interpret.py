# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reads a VTpass purchase or requery reply. A reply that does not match the documented codes is
pending, because calling a delivered order failed would invite a second purchase. The exception is
HTTP 401 or 403, which is VTpass refusing the credentials: nothing was placed."""

from typing import Any

from .api import VtpassOutcome

# Codes that VTpass documents as an order that was not processed.
FAILED_CODES = frozenset(
    {
        *("016", "091", "040", "010", "011", "012", "013", "017", "018", "019"),
        *("021", "022", "023", "024", "025", "026", "027", "028", "030", "031"),
        *("032", "034", "035", "085", "087"),
    }
)
REFUSED_STATUSES = frozenset({401, 403})
_PROCESSED_CODES = frozenset({"000", "001"})


def credentials_refused(status: int) -> VtpassOutcome:
    return VtpassOutcome(
        "failed", str(status), f"VTpass refused the credentials (HTTP {status}). The order was not placed."
    )


def no_confirmation(why: str) -> VtpassOutcome:
    """No usable reply. VTpass says to treat this as pending and requery, never as failed."""
    return VtpassOutcome("pending", None, f"No confirmation from VTpass ({why}). Checking again shortly.")


def _inner_status(payload: dict[str, Any]) -> Any:
    content = payload.get("content")
    transactions = content.get("transactions") if isinstance(content, dict) else None
    return transactions.get("status") if isinstance(transactions, dict) else None


def _description(payload: dict[str, Any]) -> str:
    described = payload.get("response_description", payload.get("message"))
    return described if isinstance(described, str) else "No description"


def _processed(code: str, inner: Any, description: str) -> VtpassOutcome:
    match inner:
        case "delivered":
            return VtpassOutcome("delivered", code, description)
        case "failed" | "reversed":
            return VtpassOutcome("failed", code, description)
        case _:
            return VtpassOutcome("pending", code, description)


def interpret_vtpass(payload: Any, http_status: int | None = None) -> VtpassOutcome:
    if http_status in REFUSED_STATUSES:
        return credentials_refused(http_status)
    if not isinstance(payload, dict):
        return no_confirmation("unreadable reply")
    code = payload.get("code")
    if not isinstance(code, str):
        return no_confirmation("no response code")
    description = _description(payload)
    if code in _PROCESSED_CODES:
        return _processed(code, _inner_status(payload), description)
    if code == "015":
        return VtpassOutcome("pending", code, description, unknown_request=True)
    if code in FAILED_CODES:
        return VtpassOutcome("failed", code, description)
    return VtpassOutcome("pending", code, description)
