# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sending what the outbox holds. A quote that ends puts one row per matching subscription in the outbox
(a trigger in migrations/0006_events.sql, so no path that ends a quote can skip it). `drain` hands each due
row to the delivery queue (jobs.py) and `deliver` sends it, signed, one event a request. A 2xx is delivered;
410 ends the subscription and 413 drops the event; anything else is tried again later, with the same event id,
up to MAX_ATTEMPTS times."""

import json
from datetime import UTC, datetime

from ..audit import Audit
from ..clock import Clock
from ..db import Db
from ..jobs import Jobs
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
        self.jobs: Jobs | None = None

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
        request and the minute's drain never hand one event on twice at once."""
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
        """Hands each row that is due to the delivery queue, once: claiming it moves it out of reach for a
        minute, and a row a crashed delivery left behind comes due again after that. The number handed on."""
        now = self._clock.now()
        handed = 0
        for row in await self._due(now):
            if await self._claim(row, now) and self.jobs is not None:
                await self.jobs.send(
                    {"kind": "deliver", "event": row["event_id"], "subscription": row["subscription_id"]}
                )
                handed += 1
        return handed

    async def deliver(self, event_id: str, subscription_id: str) -> None:
        """Sends one row, signed. An expired subscription's events are dropped."""
        row = await self._db.row(
            "SELECT o.event_id, o.subscription_id, o.data, o.occurred_at, o.attempts, o.next_at, s.url, "
            "s.secret, s.expires_at FROM event_outbox o "
            "JOIN event_subscriptions s ON s.id = o.subscription_id "
            "WHERE o.event_id = ? AND o.subscription_id = ? AND o.done_at IS NULL",
            event_id,
            subscription_id,
        )
        if row is None:
            return
        now = self._clock.now()
        if row["expires_at"] <= now:
            await self._done(row, now)
            return
        await self._settle(row, await self._send(row, now), now)
