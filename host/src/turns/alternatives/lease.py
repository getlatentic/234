# SPDX-License-Identifier: AGPL-3.0-or-later
"""A per-chat lease in D1, for runners that are not a single object: two queue deliveries or two requests
can each try to run the same chat's turn, and only the holder of the lease may. The lease expires, so a
runner that died is replaced; a runner renews it as it appends."""

import secrets

from ..db import Db

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS chat_lease "
    "(chat_id TEXT PRIMARY KEY, holder TEXT NOT NULL, until INTEGER NOT NULL) WITHOUT ROWID"
)
LEASE_MS = 30_000


class LeaseLost(Exception):
    """Another runner holds the chat now."""


class Lease:
    def __init__(self, db: Db, chat_id: str, clock) -> None:
        self._db, self._chat_id, self._clock = db, chat_id, clock
        self.holder = secrets.token_hex(8)

    async def claim(self) -> bool:
        await self._db.execute(SCHEMA)
        now = self._clock()
        changed = await self._db.execute(
            "INSERT INTO chat_lease (chat_id, holder, until) VALUES (?1, ?2, ?3) "
            "ON CONFLICT (chat_id) DO UPDATE SET holder = ?2, until = ?3 "
            "WHERE chat_lease.until < ?4 OR chat_lease.holder = ?2",
            self._chat_id, self.holder, now + LEASE_MS, now,
        )  # fmt: skip
        return changed == 1

    async def renew(self) -> None:
        changed = await self._db.execute(
            "UPDATE chat_lease SET until = ? WHERE chat_id = ? AND holder = ?",
            self._clock() + LEASE_MS, self._chat_id, self.holder,
        )  # fmt: skip
        if changed != 1:
            raise LeaseLost(self._chat_id)

    async def release(self) -> None:
        await self._db.execute(
            "DELETE FROM chat_lease WHERE chat_id = ? AND holder = ?", self._chat_id, self.holder
        )
