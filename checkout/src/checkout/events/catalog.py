# SPDX-License-Identifier: AGPL-3.0-or-later
"""The events a connector offers (MCP events, `events/list`): one, `quote.finished`, when a quote of the
account on this connector ends, with the state it ended in."""

from typing import Any

QUOTE_FINISHED = "quote.finished"
STATES = ("settled", "failed", "abandoned", "declined", "unavailable", "refund_due", "expired")


def definition(connector: str) -> dict[str, Any]:
    return {
        "name": QUOTE_FINISHED,
        "description": (
            f"A {connector} quote of this account ended: paid and delivered (settled), failed, abandoned, "
            "declined, unavailable, owed a refund (refund_due) or expired. Give quote_id to follow one quote."
        ),
        "delivery": ["webhook"],
        "inputSchema": {
            "type": "object",
            "properties": {
                "quote_id": {"type": "string", "maxLength": 64, "description": "Only this quote's ending."}
            },
            "additionalProperties": False,
        },
        "payloadSchema": {
            "type": "object",
            "properties": {
                "quote_id": {"type": "string"},
                "connector": {"type": "string"},
                "state": {"type": "string", "enum": list(STATES)},
                "amount_kobo": {"type": "integer"},
                "description": {"type": "string"},
            },
            "required": ["quote_id", "connector", "state", "amount_kobo", "description"],
            "additionalProperties": False,
        },
    }


def quote_filter(arguments: object) -> str | None:
    """The quote a subscription follows, or None for every quote; anything else is refused."""
    if not isinstance(arguments, dict) or set(arguments) - {"quote_id"}:
        raise ValueError("arguments may hold only quote_id")
    quote_id = arguments.get("quote_id")
    if quote_id is not None and (not isinstance(quote_id, str) or not 0 < len(quote_id) <= 64):
        raise ValueError("quote_id must be a string of at most 64 characters")
    return quote_id
