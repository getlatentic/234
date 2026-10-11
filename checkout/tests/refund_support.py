# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the refund tests: a quote paid at the simulated checkout that ends owing a refund, its refund as
234 keeps it, the simulated Paystack's refunds, and the test route that moves one on."""

import json

from checkout.http import handle
from checkout.paystack.api import PaystackApi
from checkout.provider_hooks import paystack
from checkout.refunds.outcome import RefundOutcomes
from checkout.refunds.record import Refund
from checkout.sim_paystack_refund import refund_event
from tests.airtime_support import paid
from tests.support import Stack

SECRET = "test-secret-not-real"
UNDELIVERABLE = "100000000000"


def refunds(stack: Stack) -> RefundOutcomes:
    return stack.app.background.rechecks.refunds


def paystack_of(stack: Stack, connector: str = "airtime") -> PaystackApi:
    return stack.app.contexts[connector].paystack


def with_paystack(stack: Stack, api: PaystackApi, connector: str = "airtime") -> None:
    """The refunds of one connector's quotes over another Paystack (one that fails or answers late)."""
    refunds(stack)._paystack = {**refunds(stack)._paystack, connector: api}


async def owed(stack: Stack) -> str:
    """Airtime paid at the checkout that VTpass could not deliver: `refund_due`, its refund asked for and not
    yet run."""
    quote_id = await paid(stack, phone=UNDELIVERABLE)
    await stack.airtime.verify(quote_id)
    return quote_id


async def delivered(stack: Stack) -> str:
    """Airtime paid at the checkout and delivered."""
    quote_id = await paid(stack)
    await stack.airtime.verify(quote_id)
    return quote_id


async def refunded(stack: Stack) -> str:
    """An owed quote whose refund was sent: Paystack holds it `pending`."""
    quote_id = await owed(stack)
    await stack.run_jobs()
    return quote_id


async def refund_of(stack: Stack, quote_id: str) -> Refund | None:
    return await refunds(stack).get(quote_id)


async def sim_refunds(stack: Stack) -> list[dict]:
    return await stack.rows("SELECT * FROM sim_refunds ORDER BY id")


async def reference_of(stack: Stack, quote_id: str) -> str:
    return (await stack.ledger.get(quote_id)).progress["paystackReference"]


async def paystack_moves(stack: Stack, quote_id: str, status: str):
    """The simulated Paystack moves the payment's refund on and sends its signed event; the work it queues
    runs."""
    reference = await reference_of(stack, quote_id)
    answer = await handle(
        stack.app, "POST", f"/test/paystack-refund/{reference}", {}, b"", f"status={status}"
    )
    await stack.run_jobs()
    return answer


async def refund_hook(stack: Stack, quote_id: str, status: str, signed: bool = True):
    """A refund event as anyone could post it: signed with the simulator's key, or not at all."""
    body = refund_event(await reference_of(stack, quote_id), status, 50_000)
    signature = paystack.sign(body, paystack.simulated_key(SECRET)) if signed else ""
    return await handle(stack.app, "POST", "/hooks/paystack", {"x-paystack-signature": signature}, body)


async def sweep(stack: Stack, after_seconds: float = 60) -> None:
    stack.clock.advance(after_seconds)
    await stack.app.background.minute()
    await stack.run_jobs()


def audited(stack: Stack, event: str) -> int:
    return [json.loads(line)["event"] for line in stack.audit_lines].count(event)
