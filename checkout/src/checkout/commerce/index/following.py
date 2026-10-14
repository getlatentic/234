# SPDX-License-Identifier: AGPL-3.0-or-later
"""Asking Index where an order it was sent stands, without sending it again. A Chowdeck order has Index's own
`track_order`. Airtime and electricity have none, so the person's Zap history is read for the debit of exactly
the quote's amount since the approval: found, the order went through; not found for an hour after the send, no
charge is known and the quote ends as failed, saying so; until then it is pending. This never places an
order."""

from datetime import UTC, datetime
from typing import Any

from ...ledger import Quote
from ..model import Outcome
from .outcomes import ORDER, named
from .reading import flat, kobo_in, listing, text_in, words
from .wire import IndexSession

WINDOW_MS = 60 * 60_000
SKEW_MS = 2 * 60_000
LAGOS_OFFSET_S = 3600
DEBITS = ("debit", "out", "outflow", "spend")
ACTIVITY = ("transactions", "activity", "entries", "items")
NO_CHARGE = (
    "Paystack Index never confirmed this order and no matching debit is in the person's Zap history, so as "
    "far "
    "as 234 can see nothing was charged. If their Zap shows a charge for it, they should tell Index."
)
WAITING = (
    "Paystack Index has not confirmed this order yet. 234 asks again and will not place it a second time."
)


def _lagos_date(at_ms: int) -> str:
    return datetime.fromtimestamp(at_ms / 1000 + LAGOS_OFFSET_S, UTC).date().isoformat()


def _when(item: dict[str, Any]) -> int | None:
    raw = text_in(item, "created_at", "date", "timestamp", "time")
    try:
        return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp() * 1000) if raw else None
    except ValueError:
        return None


def _is_the_debit(item: Any, amount_kobo: int, since_ms: int) -> bool:
    if not isinstance(item, dict) or kobo_in(item, "amount") != amount_kobo:
        return False
    direction = str(text_in(item, "type", "direction", "flow") or "debit").lower()
    when = _when(item)
    return direction in DEBITS and (when is None or when >= since_ms - SKEW_MS)


async def _zap_shows_the_debit(session: IndexSession, quote: Quote, now: int) -> bool:
    since = quote.approved_at or quote.created_at
    reply = await session.call(
        "get_recent_activity",
        {
            "source": "zap",
            "type": "debit",
            "start_date": _lagos_date(since),
            "end_date": _lagos_date(now),
            "limit": 50,
        },
    )
    if reply.is_error:
        return False
    return any(_is_the_debit(i, quote.amount_kobo, since) for i in listing(flat(reply.data), *ACTIVITY))


async def _tracked(session: IndexSession, order: str) -> Outcome:
    reply = await session.call("track_order", {"merchant_id": "chowdeck", "order_id": order})
    if reply.is_error:
        return Outcome("pending", WAITING)
    data = flat(reply.data)
    payment, status = named(text_in(data, "payment_status")), named(text_in(data, "status"))
    if "failed" in (payment, status):
        return Outcome(
            "failed", f"Chowdeck's order did not go through: {words(reply.text) or 'no reason given'}"
        )
    if payment == "pending":
        return Outcome("pending", "Chowdeck has the order and the payment is not complete yet.")
    return Outcome("delivered", "Chowdeck has the order and it is paid.")


async def follow(session: IndexSession, quote: Quote, sent_at: int, now: int) -> Outcome:
    """Where the order stands; `sent_at` is when the charging call was sent."""
    kept = (quote.progress.get("fulfilment") or {}).get("lines") or []
    order = dict((label, value) for label, value in kept).get(ORDER)
    if quote.details["index"]["kind"] == "food" and order:
        return await _tracked(session, order)
    if await _zap_shows_the_debit(session, quote, now):
        return Outcome("delivered", "The person's Zap history shows the debit, so Paystack Index placed it.")
    return Outcome("failed", NO_CHARGE) if now - sent_at >= WINDOW_MS else Outcome("pending", WAITING)
