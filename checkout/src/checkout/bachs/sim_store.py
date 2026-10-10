# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the simulated Bachs remembers, in D1 (migrations/0013_bachs_simulator.sql). Each write that must not
race is one statement: an INSERT a UNIQUE key refuses, or an UPDATE whose WHERE holds the state it leaves."""

import json
import secrets
from dataclasses import dataclass
from typing import Any

from ..db import Db, UniqueViolation


@dataclass(frozen=True)
class SimCheckout:
    checkout_id: str
    reference: str
    idempotency_key: str | None
    request_hash: str
    amount: str
    currency: str
    metadata: dict[str, Any]
    status: str
    expires_at: int
    paid_at: int | None


@dataclass(frozen=True)
class NewCheckout:
    reference: str
    idempotency_key: str | None
    request_hash: str
    amount: str
    currency: str
    email: str | None
    metadata: dict[str, Any]
    created_at: int
    expires_at: int


def _checkout(row: dict[str, Any]) -> SimCheckout:
    return SimCheckout(
        row["checkout_id"], row["reference"], row["idempotency_key"], row["request_hash"], row["amount"],
        row["currency"], json.loads(row["metadata"]), row["status"], row["expires_at"], row["paid_at"],
    )  # fmt: skip


class BachsSimStore:
    def __init__(self, db: Db) -> None:
        self._db = db

    async def add(self, new: NewCheckout) -> SimCheckout | None:
        """The checkout made now, or None when its reference or idempotency key is taken."""
        checkout_id = f"chk_{secrets.token_hex(8)}"
        try:
            await self._db.execute(
                "INSERT INTO sim_bachs_checkouts (checkout_id, reference, idempotency_key, request_hash, "
                "amount, currency, email, metadata, status, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
                checkout_id, new.reference, new.idempotency_key, new.request_hash, new.amount, new.currency,
                new.email, json.dumps(new.metadata), new.created_at, new.expires_at,
            )  # fmt: skip
        except UniqueViolation:
            return None
        return await self.checkout(checkout_id)

    async def checkout(self, checkout_id: str) -> SimCheckout | None:
        row = await self._db.row("SELECT * FROM sim_bachs_checkouts WHERE checkout_id = ?", checkout_id)
        return _checkout(row) if row else None

    async def by_idempotency_key(self, key: str) -> SimCheckout | None:
        row = await self._db.row("SELECT * FROM sim_bachs_checkouts WHERE idempotency_key = ?", key)
        return _checkout(row) if row else None

    async def pay(self, checkout_id: str, now: int) -> bool:
        """The pay page's button. Only an open checkout within its time can be paid, once."""
        changed = await self._db.execute(
            "UPDATE sim_bachs_checkouts SET status = 'paid', paid_at = ? "
            "WHERE checkout_id = ? AND status = 'open' AND expires_at > ?",
            now,
            checkout_id,
            now,
        )
        return changed == 1
