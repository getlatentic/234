# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the top-up tests: a stack with a wallet, a top-up started on it, and Bachs' webhook as Bachs
signs it."""

import json
from typing import Any

from checkout.bachs.signature import SIGNATURE_HEADER, header_for
from checkout.bachs.sim import simulated_webhook_secret
from checkout.http import handle
from checkout.wallet.topups import TopUp, owner_tag
from tests.support import ALICE, Stack

SECRET = "test-secret-not-real"
SIMULATED = simulated_webhook_secret(SECRET)
SANDBOX_KEY = "sk_" + "sandbox_" + "a1b2c3d4e5f6"
WEBHOOK_SECRET = "whsec_" + "sandbox-endpoint-1"


def topups(stack: Stack):
    return stack.app.funding.topups


async def started(stack: Stack, amount: int = 500_000, owner: str = ALICE) -> TopUp:
    await topups(stack).journal.open(owner)
    return await topups(stack).start(owner, amount)


def succeeded(topup: TopUp, **data: Any) -> bytes:
    """The `collection.succeeded` Bachs sends for this top-up; `data` changes any of its fields."""
    body = {
        "id": "evt_3ab4e0d5d27445cf8a52ab3d8cb8f0b1",
        "type": "collection.succeeded",
        "created_at": "2026-09-29T10:00:00.000Z",
        "organization_id": "acct_7KpQ2mNv4XbR9dLc",
        "data": {
            "charge_id": "ch_1a2b3c4d5e6f",
            "checkout_id": topup.provider_ref,
            "reference": topup.id,
            "status": "SUCCEEDED",
            "amount": f"{topup.amount_kobo // 100}.{topup.amount_kobo % 100:02d}",
            "currency": "NGN",
            "fee_bearer": "merchant",
            "metadata": {"wallet_topup": topup.id, "wallet_owner": owner_tag(topup.owner)},
            **data,
        },
    }
    return json.dumps(body).encode()


async def deliver(stack: Stack, body: bytes, secrets: tuple[str, ...] = (SIMULATED,), at: int | None = None):
    """One delivery to /hooks/bachs, signed with each secret at `at` (unix seconds; now by default)."""
    stamp = stack.clock.now() // 1000 if at is None else at
    headers = {SIGNATURE_HEADER: header_for(secrets, stamp, body)}
    return await handle(stack.app, "POST", "/hooks/bachs", headers, body)


async def balance(stack: Stack, owner: str = ALICE) -> int:
    return await topups(stack).journal.balance(owner)


async def funds(stack: Stack) -> list[dict]:
    return await stack.rows("SELECT * FROM wallet_entry WHERE kind = 'fund' ORDER BY seq")


async def state_of(stack: Stack, topup: TopUp) -> str:
    found = await topups(stack).get(topup.id)
    assert found is not None
    return found.state


def audited(stack: Stack, event: str) -> list[dict]:
    return [line for line in map(json.loads, stack.audit_lines) if line["event"] == event]
