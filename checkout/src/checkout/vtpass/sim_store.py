# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the simulated VTpass remembers, in D1."""

from dataclasses import dataclass
from typing import Any

from ..db import Db


@dataclass(frozen=True)
class SimOrder:
    request_id: str
    service_id: str
    phone: str
    amount_naira: float
    variation_code: str | None
    scenario: str
    created_at: int
    reversed_at: int | None = None
    billers_code: str | None = None
    subscription_type: str | None = None


def _order(row: dict[str, Any]) -> SimOrder:
    return SimOrder(
        row["request_id"], row["service_id"], row["phone"], row["amount_naira"],
        row["variation_code"], row["scenario"], row["created_at"], row["reversed_at"],
        row["billers_code"], row["subscription_type"],
    )  # fmt: skip


class VtpassSimStore:
    def __init__(self, db: Db) -> None:
        self._db = db

    async def add(self, order: SimOrder) -> bool:
        """False when the request id is taken: VTpass answers a repeated id with code 014."""
        changed = await self._db.execute(
            "INSERT OR IGNORE INTO sim_vtpass "
            "(request_id, service_id, phone, amount_naira, variation_code, scenario, created_at, "
            "billers_code, subscription_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            order.request_id, order.service_id, order.phone, order.amount_naira,
            order.variation_code, order.scenario, order.created_at, order.billers_code,
            order.subscription_type,
        )  # fmt: skip
        return changed == 1

    async def get(self, request_id: str) -> SimOrder | None:
        row = await self._db.row("SELECT * FROM sim_vtpass WHERE request_id = ?", request_id)
        return _order(row) if row else None

    async def reverse(self, request_id: str, at: int) -> SimOrder | None:
        """Takes back an order the simulator delivers; None for any other, or one already taken back."""
        changed = await self._db.execute(
            "UPDATE sim_vtpass SET reversed_at = ? WHERE request_id = ? AND reversed_at IS NULL "
            "AND scenario IN ('success', 'pending')",
            at,
            request_id,
        )
        return await self.get(request_id) if changed == 1 else None
