# SPDX-License-Identifier: AGPL-3.0-or-later
"""Subscriptions, kept in D1 and scoped by owner like quotes. A subscription's id is derived from who asked,
what for and where to, so subscribing again is a refresh of the same one."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ..db import Db

DEFAULT_TTL_MS = 7 * 24 * 3600 * 1000
MAX_TTL_MS = 30 * 24 * 3600 * 1000


@dataclass(frozen=True)
class Request:
    owner: str
    connector: str
    name: str
    arguments: dict[str, Any]
    url: str

    @property
    def id(self) -> str:
        canonical = json.dumps(self.arguments, sort_keys=True, separators=(",", ":"))
        identity = "\n".join((self.owner, self.connector, self.name, canonical, self.url))
        return "sub_" + hashlib.sha256(identity.encode()).hexdigest()[:32]


def granted_ttl(asked: object) -> int:
    """The lifetime given: 7 days by default, at most 30, and never indefinite."""
    if asked is None:
        return DEFAULT_TTL_MS
    if not isinstance(asked, int) or isinstance(asked, bool) or asked <= 0:
        raise ValueError("ttlMs must be a positive whole number of milliseconds")
    return min(asked, MAX_TTL_MS)


class Subscriptions:
    def __init__(self, db: Db) -> None:
        self._db = db

    async def exists(self, subscription_id: str) -> bool:
        return (
            await self._db.row("SELECT 1 FROM event_subscriptions WHERE id = ?", subscription_id) is not None
        )

    async def save(
        self, asked: Request, quote_id: str | None, secret: str, expires_at: int, now: int
    ) -> None:
        await self._db.execute(
            "INSERT INTO event_subscriptions (id, owner, connector, name, quote_id, arguments, url, secret, "
            "expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET secret = excluded.secret, expires_at = excluded.expires_at",
            asked.id,
            asked.owner,
            asked.connector,
            asked.name,
            quote_id,
            json.dumps(asked.arguments, sort_keys=True),
            asked.url,
            secret,
            expires_at,
            now,
        )

    async def remove(self, subscription_id: str, owner: str) -> None:
        await self._db.batch(
            [
                ("DELETE FROM event_subscriptions WHERE id = ? AND owner = ?", (subscription_id, owner)),
                (
                    "DELETE FROM event_outbox WHERE subscription_id = ? AND done_at IS NULL",
                    (subscription_id,),
                ),
            ]
        )
