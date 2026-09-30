# SPDX-License-Identifier: AGPL-3.0-or-later
"""The quotes of a chat as its log tells them: which are still open, and where each one's flow begins.

A quote's card is recorded when it is made, and every change of its state after that. The phase it was last
seen in, and its expiry, say whether the person can still act on it. A quote that can be acted on must stay
in front of the model word for word; the others may be summarised.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .. import kinds
from ..eventlog import Event

OPEN_PHASES = frozenset({"awaiting_approval", "awaiting_checkout", "awaiting_otp", "processing"})
APPROVAL_PHASE = "awaiting_approval"


@dataclass(frozen=True)
class QuoteFact:
    ref: str
    phase: str
    kobo: int | None
    what: str
    seq: int
    expires_ms: int | None

    def is_open(self, now_ms: int) -> bool:
        """Open while its phase waits on the person or the payment, unless it was never approved and its time
        has run out: its card then says expired when pressed, and nothing more can be done with it."""
        if self.phase not in OPEN_PHASES:
            return False
        return not (self.phase == APPROVAL_PHASE and self.expires_ms is not None and self.expires_ms < now_ms)


def view_of(event: Event) -> dict[str, Any]:
    quote = ((event.payload.get("result") or {}).get("structuredContent") or {}).get("quote")
    return quote if isinstance(quote, dict) else {}


def _expiry(quote: dict[str, Any]) -> int | None:
    try:
        return int(datetime.fromisoformat(quote["expiresAt"]).timestamp() * 1000)
    except KeyError, TypeError, ValueError:
        return None


def _what(quote: dict[str, Any]) -> str:
    details = quote.get("details") or {}
    return str(details.get("readBack") or quote.get("description") or quote.get("merchant") or "")


def quotes_of(events: list[Event]) -> list[QuoteFact]:
    """Each quote that has a card, in the order the cards were made, as it last stood."""
    found: dict[str, QuoteFact] = {}
    for event in events:
        quote = view_of(event)
        if event.type not in (kinds.CARD, kinds.CARD_STATE) or not quote or not event.ref:
            continue
        before = found.get(event.ref)
        amount = (quote.get("amount") or {}).get("kobo")
        found[event.ref] = QuoteFact(
            event.ref,
            str(quote.get("phase") or (before.phase if before else "")),
            amount if isinstance(amount, int) else (before.kobo if before else None),
            _what(quote) or (before.what if before else ""),
            before.seq if before else event.seq,
            _expiry(quote) or (before.expires_ms if before else None),
        )
    return list(found.values())


def flow_start(events: list[Event], quote: QuoteFact) -> int:
    """Where the flow of this quote begins: the reply whose call made it, or its card when a card made it."""
    card = next((e for e in events if e.type == kinds.CARD and e.ref == quote.ref), None)
    if card is None:
        return quote.seq
    made_by = next(
        (e for e in reversed(events) if e.seq < card.seq and e.type == kinds.TOOL and e.task == card.task),
        None,
    )
    if made_by is None:
        return card.seq
    reply = next(
        (
            e
            for e in events
            if e.type == kinds.ASSISTANT
            and any(c["id"] == made_by.payload["call_id"] for c in e.payload.get("tool_calls", []))
        ),
        None,
    )
    return reply.seq if reply else card.seq


def open_floor(events: list[Event], now_ms: int) -> int | None:
    """The seq from which the events must stay verbatim so that the latest open quote is whole in front of the
    model, or None when no quote is open."""
    open_quotes = [q for q in quotes_of(events) if q.is_open(now_ms)]
    return flow_start(events, max(open_quotes, key=lambda q: q.seq)) if open_quotes else None


def open_refs_before(events: list[Event], last: int, now_ms: int) -> frozenset[str]:
    """The quotes still open whose cards were made at or before seq `last`."""
    return frozenset(q.ref for q in quotes_of(events) if q.seq <= last and q.is_open(now_ms))
