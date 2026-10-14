# SPDX-License-Identifier: AGPL-3.0-or-later
"""What every simulated Index tool shares: the account a call is for, the answer a tool gives, and the charge.
A charge is the only thing that takes money from the account, and what happens to it is set by the test routes
(`confirm_outcome`): `delivered`, `failed` (Index refuses, nothing taken), `pending` (taken, not finished),
`dropped` (taken, the answer lost on the way) and `lost` (nothing taken, the answer lost)."""

from dataclasses import dataclass, field
from typing import Any

from ...clock import Clock
from .sim_store import IndexSimStore, SimAccount

OUTCOME_SETTING = "confirm_outcome"
OUTCOMES = ("delivered", "failed", "pending", "dropped", "lost")


@dataclass(frozen=True)
class ToolAnswer:
    data: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    error: bool = False
    fate: str = "ok"
    """`ok`, or `drop`: the transport loses the answer after the tool ran."""


def refusal(text: str) -> ToolAnswer:
    return ToolAnswer({}, text, True)


def success(text: str, data: dict[str, Any]) -> ToolAnswer:
    return ToolAnswer(data, text)


@dataclass(frozen=True)
class SimContext:
    store: IndexSimStore
    clock: Clock
    account: SimAccount | None

    async def charge(
        self, tool: str, arguments: dict[str, Any], total: int, detail: dict[str, Any]
    ) -> ToolAnswer:
        """Takes `total` from the account's Zap as the setting says, and records the order."""
        assert self.account is not None
        outcome = await self.store.setting(OUTCOME_SETTING, "delivered")
        if outcome == "lost":
            return ToolAnswer(fate="drop")
        if outcome == "failed" or not await self.store.debit(self.account.id, total):
            return refusal("Index could not complete the purchase. Your Zap was not charged.")
        status = "pending" if outcome == "pending" else "completed"
        order = await self.store.add_order(self.account.id, tool, arguments, total, status, detail)
        reply = {"status": status, "order_id": order, **detail}
        return ToolAnswer(reply, f"Order {order}: {status}.", fate="drop" if outcome == "dropped" else "ok")
