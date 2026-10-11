# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the card says of a payment owed back: refunding, refunded, or 234 following it up. It reads the
refund's state the quote's progress mirrors (refunds/outcome.py), so the card needs no other read."""

from typing import Any

from ..ledger import Quote
from ..money import format_naira
from .owed import owes_refund

FOLLOW_UP = "234 will follow up."


def refund_state(quote: Quote) -> str | None:
    return (quote.progress.get("refund") or {}).get("state")


def is_refunded(quote: Quote) -> bool:
    return quote.state == "refunded" or refund_state(quote) == "processed"


def _words(quote: Quote) -> tuple[str, str]:
    """The card's status and the sentence that says where the money is."""
    amount = format_naira(quote.amount_kobo)
    state = refund_state(quote)
    if is_refunded(quote):
        return f"Refunded {amount}", f"{amount} was refunded to the card or account that paid."
    if not owes_refund(quote) or state == "refused":
        return "Refund due", f"A refund is due. {FOLLOW_UP}"
    if state == "failed":
        return "Refund failed", f"The refund failed. {FOLLOW_UP}"
    if state == "needs_attention":
        return "Refund delayed", f"Paystack needs the payer's bank account to refund {amount}. {FOLLOW_UP}"
    return f"Refunding {amount}", f"{amount} is being refunded to the card or account that paid."


def refund_view(quote: Quote, reason: str) -> tuple[dict[str, Any], str]:
    """The card's `refund` and its message: what went wrong, then where the money is."""
    title, said = _words(quote)
    return {"title": title, "state": refund_state(quote)}, f"{reason} {said}"
