# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the connect card shows, worked out from the truth each time it asks: the attempt (the card's own
record), the person's connection, and whether the merchant on the card still has to be linked. The state is
never kept; a card that is old, or open in two tabs, shows what is so now."""

from typing import Any

from .attempts import Attempt
from .catalog import Entry
from .store import Connection

PROVIDER = "Paystack Index"
POLL_SECONDS = 3


def needs_linking(entry: Entry | None, connection: Connection) -> bool:
    return entry is not None and entry.asks_link and entry.index_id not in connection.linked


def state_of(attempt: Attempt, connection: Connection | None, entry: Entry | None, now: int) -> str:
    """`authorize`, `phone`, `code`, `connected`, `denied`, `expired` or `disconnected`."""
    if attempt.status == "ended":
        return "disconnected"
    if connection is not None:
        if not needs_linking(entry, connection):
            return "connected"
        return "code" if attempt.step == "code" else "phone"
    if attempt.status == "denied":
        return "denied"
    gone = attempt.step != "authorize"
    return "expired" if attempt.status == "expired" or attempt.expires_at <= now or gone else "authorize"


def view_of(
    attempt: Attempt,
    connection: Connection | None,
    entry: Entry | None,
    now: int,
    link: str | None = None,
    notice: str | None = None,
) -> dict[str, Any]:
    state = state_of(attempt, connection, entry, now)
    shown: dict[str, Any] = {
        "provider": PROVIDER,
        "merchant": entry.name if entry else None,
        "state": state,
        "interval": POLL_SECONDS,
    }
    if link and state == "authorize":
        shown["link"] = link
    if notice:
        shown["notice"] = notice
    return {"card_id": attempt.id, "connection": shown}
