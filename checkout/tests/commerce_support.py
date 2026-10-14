# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the commerce tests: a quote request to the `merchants` connector, a directory merchant added for
a test, an approval, and a paid order."""

import itertools
import json
from typing import Any

from checkout.errors import DomainError
from checkout.http import handle
from checkout.owner import DEFAULT_OWNER
from tests.support import ALICE, Stack
from tests.wallet_card_support import call

CONNECTOR = "merchants"
MAMA = "mama-put-yaba"
WATER = "eko-prepaid-water"
PHARMACY = "lagosmed-pharmacy"
GROCER = "ikeja-fresh-grocer"
NOW = 1_791_936_000_000
_keys = itertools.count(1)


def new_key() -> str:
    return f"commerce-key-{next(_keys):05d}"


def meal(**over: Any) -> dict[str, Any]:
    """A quote request for two jollof and a zobo from Mama Put: 2 x 4,500 + 800 + 1,200 delivery = 11,000."""
    return {
        "merchant_id": MAMA,
        "lines": [{"offer_id": "jollof-chicken", "quantity": 2}, {"offer_id": "zobo"}],
        "fields": {"area": "Yaba"},
        "idempotency_key": new_key(),
        **over,
    }


MEAL_KOBO = 1_100_000


def water_bill(check_id: str | None, **over: Any) -> dict[str, Any]:
    """A water credit of 5,000 naira to a checked account."""
    return {
        "merchant_id": WATER,
        "lines": [{"offer_id": "water-credit"}],
        "amount_kobo": 500_000,
        "amount_as_user_said": "5000",
        "fields": {"meter_number": "10012345"},
        "check_id": check_id,
        "idempotency_key": new_key(),
        **over,
    }


async def quote(stack: Stack, owner: str | None = None, **over: Any) -> dict[str, Any]:
    arguments = meal(**over)
    if owner is None:
        return await stack.call(CONNECTOR, "create_quote", **arguments)
    return await stack.call_as(owner, CONNECTOR, "create_quote", **arguments)


async def checked(stack: Stack, number: str = "10012345") -> str:
    """The check_id of a water account the simulated Eko Water knows."""
    result = await stack.call(CONNECTOR, "check_account", merchant_id=WATER, fields={"meter_number": number})
    assert "isError" not in result, result["content"][0]["text"]
    return result["structuredContent"]["check_id"]


async def refusal(work) -> str:
    try:
        await work
    except DomainError as error:
        return error.code
    return "none"


async def add_merchant(stack: Stack, merchant_id: str = "test-shop", **over: Any) -> None:
    """A directory merchant of a test's own, with a fixed price offer `item` at 2,000 naira."""
    columns = {
        "id": merchant_id,
        "name": "Test Shop",
        "category": "shop",
        "status": "live",
        "requires_link": 0,
        "blurb": "A shop made for a test.",
        "min_kobo": 100_000,
        "max_kobo": 5_000_000,
        "fee_label": "Delivery",
        "fee_kobo": 0,
        "checks_account": 0,
        "fields": "[]",
        "created_at": NOW,
        "updated_at": NOW,
        **over,
    }
    names = ", ".join(columns)
    marks = ", ".join("?" for _ in columns)
    await stack.db.execute(f"INSERT INTO merchant ({names}) VALUES ({marks})", *columns.values())
    await add_offer(stack, merchant_id, "item", name="Item", price_kobo=200_000)


async def add_offer(stack: Stack, merchant_id: str, offer_id: str, **over: Any) -> None:
    columns = {
        "merchant_id": merchant_id,
        "id": offer_id,
        "name": "Offer",
        "description": "",
        "tags": "",
        "price_kind": "fixed",
        "price_kobo": 100_000,
        "min_kobo": None,
        "max_kobo": None,
        "available": 1,
        "max_quantity": 10,
        "option_groups": "[]",
        "position": 0,
        "created_at": NOW,
        "updated_at": NOW,
        **over,
    }
    names = ", ".join(columns)
    marks = ", ".join("?" for _ in columns)
    await stack.db.execute(f"INSERT INTO offer ({names}) VALUES ({marks})", *columns.values())


async def fund(stack: Stack, amount: int, owner: str = DEFAULT_OWNER, ref: str = "top-up-1") -> None:
    journal = stack.app.contexts[CONNECTOR].wallet.journal
    assert await journal.credit(owner, "fund", amount, ref) is not None


def approval(made: dict[str, Any], **over: Any) -> dict[str, Any]:
    view = made["structuredContent"]["quote"]
    return {
        "quote_id": view["id"],
        "approval_token": made["_meta"]["approvalToken"],
        "displayed_amount_kobo": view["amount"]["kobo"],
        **over,
    }


async def approved_and_paid(stack: Stack, made: dict[str, Any]) -> dict[str, Any]:
    """The quote approved and paid on the simulated checkout: the card's view after the last check."""
    approved = await stack.call(CONNECTOR, "approve_quote", **approval(made))
    assert "isError" not in approved, approved["content"][0]["text"]
    await stack.complete_checkout(approved["structuredContent"]["quote"]["checkoutUrl"], "success")
    return await stack.call(CONNECTOR, "verify_quote", quote_id=approved["structuredContent"]["quote"]["id"])


async def as_account(stack: Stack, tool: str, owner: str = ALICE, **arguments: Any) -> dict[str, Any]:
    """A call to the merchants connector as a signed-in account, which is the only one with a wallet."""
    return (await call(stack, CONNECTOR, tool, owner, True, **arguments))["result"]


async def stored(stack: Stack, quote_id: str) -> dict[str, Any]:
    """The quote's row as stored, whoever owns it: its state and its progress read as JSON."""
    row = await stack.db.row("SELECT state, progress FROM quotes WHERE id = ?", quote_id)
    assert row is not None
    return {"state": row["state"], "progress": json.loads(row["progress"])}


async def answer(stack: Stack, quote_id: str, outcome: str):
    """The simulated merchant answers the quote's order (the test route): delivered, pending or failed."""
    return await handle(stack.app, "POST", f"/test/merchant-order/{quote_id}", {}, b"", f"outcome={outcome}")
