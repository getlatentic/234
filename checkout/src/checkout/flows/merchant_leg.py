# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fulfilling a paid `merchants` quote through its provider, guarded the way airtime is: the request id is
fixed once per quote by one conditional write, one caller at a time holds the provider step, and the answer
is recorded by a statement that applies only while the quote is still approved. The outcome is one of three:
delivered ends the quote, failed leaves a refund owed, and anything else is pending and asked about again
with `status`, never placed again (docs/commerce.md, rule 6)."""

from typing import Any

from ..commerce.model import Outcome
from ..commerce.registry import Providers
from ..errors import DomainError
from ..ledger import Quote
from .checkout_leg import STEP_STALE_MS, ask_refund
from .context import Context

CONNECTOR = "merchants"


def _request_id(quote: Quote) -> str:
    return f"mrq-{quote.id}"


async def _fulfilment(ctx: Context, quote: Quote) -> dict[str, Any]:
    """The order's request id and how many times its provider has been asked, fixed once per quote."""
    if quote.progress.get("fulfilment"):
        return quote.progress["fulfilment"]
    proposed = {"requestId": _request_id(quote), "status": "pending", "attempts": 0}
    if await ctx.ledger.set_progress_once(quote.id, "fulfilment", proposed):
        ctx.audit.log("fulfilment.started", quote=quote.id, request=proposed["requestId"])
    current = await ctx.ledger.get(quote.id)
    return current.progress["fulfilment"] if current else proposed


async def _ask(providers: Providers, quote: Quote, fulfilment: dict[str, Any]) -> Outcome:
    provider = providers.named(quote.details["provider"])
    if fulfilment["attempts"] == 0:
        return await provider.fulfil(quote)
    return await provider.status(quote)


async def deliver(ctx: Context, providers: Providers, quote: Quote) -> Quote:
    """Asks the merchant's provider about a paid quote, once at a time, and records the answer."""
    ledger = ctx.ledger
    fulfilment = await _fulfilment(ctx, quote)
    if not await ledger.acquire_step(quote.id, STEP_STALE_MS):
        return await ledger.require(quote.id, CONNECTOR)
    try:
        outcome = await _ask(providers, quote, fulfilment)
    except Exception:
        await ledger.patch_progress(quote.id, {"inFlightSince": None})
        raise
    return await _record(ctx, quote, fulfilment, outcome)


async def _record(ctx: Context, quote: Quote, before: dict[str, Any], outcome: Outcome) -> Quote:
    """Writes what the provider said and lets go of the provider step in one statement that applies only
    while the quote is still approved."""
    ledger, audit = ctx.ledger, ctx.audit
    seen = {
        "requestId": before["requestId"],
        "status": outcome.status,
        "description": outcome.description,
        "attempts": before["attempts"] + 1,
    }
    patch: dict[str, Any] = {"fulfilment": seen, "inFlightSince": None}
    try:
        match outcome.status:
            case "delivered":
                audit.log("fulfilment.delivered", quote=quote.id, request=before["requestId"])
                return await ledger.transition(quote.id, ("approved",), "settled", patch)
            case "failed" | "reversed":
                audit.log("fulfilment.failed", quote=quote.id, status=outcome.status)
                audit.log("refund.due", quote=quote.id, why="paid, not delivered")
                reason = f"{quote.merchant} did not deliver: {outcome.description}"
                owed = await ledger.transition(
                    quote.id, ("approved",), "refund_due", {**patch, "failureReason": reason}
                )
                return await ask_refund(ctx, owed)
            case _:
                if before["attempts"] == 0:
                    audit.log("fulfilment.pending", quote=quote.id)
                return await ledger.patch_progress(quote.id, patch, only_state="approved")
    except DomainError:
        return await ledger.require(quote.id, CONNECTOR)
