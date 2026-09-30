# SPDX-License-Identifier: AGPL-3.0-or-later
"""How far a paid order has got. It is a stand-in: the step follows the clock, not a kitchen."""

from typing import Any

ORDER_STEPS = ("Order accepted", "Being prepared", "On the way", "Delivered")
LAST_STEP = len(ORDER_STEPS) - 1


def step_of(order_placed_at: int | None, now: int, step_ms: int) -> int | None:
    if order_placed_at is None:
        return None
    return min(max(now - order_placed_at, 0) // step_ms, LAST_STEP)


def tracking_of(
    quote_state: str, kind: str, progress: dict[str, Any], now: int, step_ms: int
) -> dict[str, Any] | None:
    if kind != "food" or quote_state == "settled":
        return None
    current = step_of(progress.get("orderPlacedAt"), now, step_ms)
    return None if current is None else {"steps": list(ORDER_STEPS), "current": current}
