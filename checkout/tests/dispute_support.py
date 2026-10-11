# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the dispute tests: a top-up paid through Bachs' webhook, and Bachs' dispute events on its charge
as Bachs signs them."""

import json
from typing import Any

from checkout.wallet.disputes import DisputeRecord
from checkout.wallet.topups import TopUp
from tests.support import ALICE, Stack
from tests.topup_support import charge_of, deliver, started, succeeded

DISPUTE = "dsp_8f1c2a9b7e3d4c5a"


async def paid(stack: Stack, amount: int = 500_000, owner: str = ALICE) -> TopUp:
    topup = await started(stack, amount, owner)
    assert (await deliver(stack, succeeded(topup))).status == 200
    found = await stack.app.funding.topups.get(topup.id)
    assert found is not None and found.state == "paid"
    return found


def disputed(
    topup: TopUp,
    status: str = "needs_response",
    event: str = "dispute.created",
    dispute_id: str = DISPUTE,
    **data: Any,
) -> bytes:
    """The dispute event Bachs sends about this top-up's charge; `data` changes any of its fields."""
    amount = f"{topup.amount_kobo // 100}.{topup.amount_kobo % 100:02d}"
    body = {
        "id": f"evt_{event}_{status}",
        "type": event,
        "created_at": "2026-10-11T10:00:00.000Z",
        "data": {
            "dispute_id": dispute_id,
            "charge_id": charge_of(topup),
            "amount": amount,
            "currency": "NGN",
            "status": status,
            "reason": "fraudulent",
            "response_deadline_at": "2026-10-18T10:00:00.000Z",
            "charge_amount": amount,
            "charge_currency": "NGN",
            **data,
        },
    }
    return json.dumps(body).encode()


async def dispute_event(stack: Stack, topup: TopUp, status: str = "needs_response", **more: Any) -> None:
    answer = await deliver(stack, disputed(topup, status, **more))
    assert answer.status == 200 and json.loads(answer.body) == {"received": True}


async def record(stack: Stack, dispute_id: str = DISPUTE) -> DisputeRecord:
    found = await stack.app.funding.hook.disputes.get(dispute_id)
    assert found is not None
    return found


async def kinds(stack: Stack, owner: str = ALICE) -> list[tuple[str, int]]:
    rows = await stack.rows("SELECT kind, amount_kobo FROM wallet_entry WHERE owner = ? ORDER BY seq", owner)
    return [(row["kind"], row["amount_kobo"]) for row in rows]


async def freezes(stack: Stack, owner: str = ALICE) -> list[dict]:
    return await stack.rows("SELECT * FROM wallet_freeze WHERE owner = ? ORDER BY created_at", owner)


async def blocks(stack: Stack, owner: str = ALICE) -> list[dict]:
    return await stack.rows("SELECT * FROM wallet_withdrawal_block WHERE owner = ?", owner)
