# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sending what the outbox holds. A quote that ends puts one row per matching subscription in the outbox
(a trigger in migrations/0006_events.sql, so no path that ends a quote can skip it); this sends each row,
signed, one event a request. A 2xx is delivered; 410 ends the subscription and 413 drops the event;
anything else is tried again later, with the same event id, up to MAX_ATTEMPTS times."""

import json
from datetime import UTC, datetime

from ..audit import Audit
from ..clock import Clock
from ..db import Db
from ..transport import Transport, TransportError
from .catalog import QUOTE_FINISHED
from .signing import headers

TIMEOUT_SECONDS = 5.0
BATCH = 20
MAX_ATTEMPTS = 8
FIRST_RETRY_MS = 30_000
LAST_RETRY_MS = 3_600_000
LEASE_MS = 60_000


def iso(at_ms: int) -> str:
    return datetime.fromtimestamp(at_ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def body_of(row: dict) -> str:
    event = {
        "eventId": row["event_id"],
        "name": QUOTE_FINISHED,
        "timestamp": iso(row["occurred_at"]),
        "data": json.loads(row["data"]),
        "cursor": None,
    }
    return json.dumps(event, separators=(",", ":"))


def retry_after(attempts: int) -> int:
    return min(LAST_RETRY_MS, FIRST_RETRY_MS * 2 ** max(attempts - 1, 0))


class Delivery:
    def __init__(self, db: Db, transport: Transport, clock: Clock, audit: Audit) -> None:
        self._db, self._transport, self._clock, self._audit = db, transport, clock, audit

    async def _due(self, now: int) -> list[dict]:
        return await self._db.rows(
            "SELECT o.event_id, o.subscription_id, o.data, o.occurred_at, o.attempts, o.next_at, s.url, "
            "s.secret, s.expires_at FROM event_outbox o "
            "JOIN event_subscriptions s ON s.id = o.subscription_id "
            "WHERE o.done_at IS NULL AND o.next_at <= ? ORDER BY o.next_at LIMIT ?",
            now,
            BATCH,
        )

    async def _claim(self, row: dict, now: int) -> bool:
        """One sender per row: a conditional update moves it out of reach for a minute, so a drain after a
        request and the minute's drain never send one event twice at once."""
        changed = await self._db.execute(
            "UPDATE event_outbox SET next_at = ? WHERE event_id = ? AND subscription_id = ? AND next_at = ? "
            "AND done_at IS NULL",
            now + LEASE_MS,
            row["event_id"],
            row["subscription_id"],
            row["next_at"],
        )
        return changed == 1

    async def _done(self, row: dict, now: int) -> None:
        await self._db.execute(
            "UPDATE event_outbox SET done_at = ?, attempts = attempts + 1 WHERE event_id = ? "
            "AND subscription_id = ?",
            now,
            row["event_id"],
            row["subscription_id"],
        )

    async def _later(self, row: dict, now: int) -> None:
        attempts = row["attempts"] + 1
        await self._db.execute(
            "UPDATE event_outbox SET attempts = ?, next_at = ?, done_at = CASE WHEN ? >= ? THEN ? END "
            "WHERE event_id = ? AND subscription_id = ?",
            attempts,
            now + retry_after(attempts),
            attempts,
            MAX_ATTEMPTS,
            now,
            row["event_id"],
            row["subscription_id"],
        )

    async def _send(self, row: dict, now: int) -> int | None:
        body = body_of(row)
        try:
            reply = await self._transport.send(
                "POST",
                row["url"],
                headers=headers(row["secret"], row["event_id"], now // 1000, body, row["subscription_id"]),
                body=body,
                timeout_seconds=TIMEOUT_SECONDS,
            )
        except TransportError:
            return None
        return reply.status

    async def _settle(self, row: dict, status: int | None, now: int) -> None:
        if (status is not None and 200 <= status < 300) or status == 413:
            await self._done(row, now)
        elif status == 410:
            await self._done(row, now)
            await self._db.execute("DELETE FROM event_subscriptions WHERE id = ?", row["subscription_id"])
        else:
            await self._later(row, now)
        self._audit.log("event.sent", event_id=row["event_id"], status=status, attempt=row["attempts"] + 1)

    async def drain(self) -> int:
        """Sends what is due now; the number of rows tried. An expired subscription's events are dropped."""
        now = self._clock.now()
        rows = await self._due(now)
        for row in rows:
            if not await self._claim(row, now):
                continue
            if row["expires_at"] <= now:
                await self._done(row, now)
                continue
            await self._settle(row, await self._send(row, now), now)
        return len(rows)
