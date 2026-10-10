# SPDX-License-Identifier: AGPL-3.0-or-later
"""The payment leg every connector shares: start Paystack's hosted checkout for an approved quote, and
ask Paystack what became of it."""

from dataclasses import dataclass
from typing import Any

from ..errors import DomainError
from ..ids import transaction_reference
from ..ledger import Quote
from ..money import format_naira
from ..paystack.api import CheckoutRequest, PaystackError, TransactionCheck
from ..wallet.spending import paid_from_wallet
from .context import Context
from .provider_error import as_domain_error

STEP_STALE_MS = 30_000


@dataclass(frozen=True)
class PaymentCheck:
    quote: Quote
    paid: bool


async def begin_checkout(ctx: Context, quote: Quote) -> Quote:
    """Starts the checkout for an approved quote. If Paystack never took the request, the approval is
    put back so the person can approve again and nothing stays reserved."""
    ledger = ctx.ledger
    if quote.state != "approved" or "checkoutUrl" in quote.progress or paid_from_wallet(quote):
        return quote
    if not await ledger.acquire_step(quote.id, STEP_STALE_MS):
        raise DomainError(
            "APPROVAL_IN_PROGRESS",
            "This approval is already being processed. Wait a moment and check the card.",
        )
    attempt = int(quote.progress.get("attempt", 0)) + 1
    reference = transaction_reference(quote.id, attempt)
    try:
        checkout = await ctx.paystack.initialize_transaction(
            CheckoutRequest(quote.amount_kobo, ctx.payer_email, reference, quote.id, quote.description)
        )
    except PaystackError as error:
        await ledger.patch_progress(quote.id, {"attempt": attempt, "inFlightSince": None})
        await ledger.release_approval(quote.id)
        ctx.audit.log("approval.released", quote=quote.id, why="checkout could not start")
        raise as_domain_error(error, "start the checkout") from error
    ctx.audit.log("checkout.started", quote=quote.id, reference=reference)
    progress: dict[str, Any] = {
        "attempt": attempt,
        "paystackReference": reference,
        "checkoutUrl": checkout.authorization_url,
        "inFlightSince": None,
    }
    if ctx.inline_checkout:
        progress["accessCode"] = checkout.access_code
    return await ledger.patch_progress(quote.id, progress)


def _past_window(ctx: Context, quote: Quote) -> bool:
    return ctx.clock.now() >= (quote.approved_at or 0) + ctx.checkout_window_seconds * 1000


def _refund_reason(quote: Quote, check: TransactionCheck) -> str | None:
    if quote.state == "abandoned":
        return "The payment arrived after the checkout had been closed."
    if check.amount_kobo != quote.amount_kobo or check.currency != "NGN":
        return (
            f"Paystack reported {format_naira(check.amount_kobo)} {check.currency} paid "
            f"for a {format_naira(quote.amount_kobo)} quote."
        )
    return None


async def _settle_success(ctx: Context, quote: Quote, check: TransactionCheck) -> PaymentCheck:
    reason = _refund_reason(quote, check)
    if reason is not None:
        ctx.audit.log("refund.due", quote=quote.id, why=reason)
        refunded = await ctx.ledger.transition(
            quote.id, (quote.state,), "refund_due", {"failureReason": reason}
        )
        return PaymentCheck(refunded, False)
    patch: dict[str, Any] = {"paymentStatus": "success"}
    if check.paid_at:
        patch["paidAt"] = check.paid_at
    if check.gateway_response:
        patch["gatewayResponse"] = check.gateway_response
    return PaymentCheck(await ctx.ledger.patch_progress(quote.id, patch), True)


async def _settle_stopped(
    ctx: Context, quote: Quote, check: TransactionCheck, checkout_closed: bool
) -> Quote:
    ledger = ctx.ledger
    gateway = check.gateway_response or check.status
    if check.status in ("failed", "reversed"):
        ctx.audit.log("payment.failed", quote=quote.id, status=check.status)
        return await ledger.transition(
            quote.id, ("approved",), "failed", {"paymentStatus": check.status, "gatewayResponse": gateway}
        )
    give_up = _past_window(ctx, quote) or (checkout_closed and check.status == "abandoned")
    if not give_up:
        return await ledger.patch_progress(quote.id, {"paymentStatus": check.status})
    ctx.audit.log("payment.abandoned", quote=quote.id)
    return await ledger.transition(quote.id, ("approved",), "abandoned", {"paymentStatus": check.status})


async def check_payment(ctx: Context, quote: Quote, checkout_closed: bool) -> PaymentCheck:
    """Asks Paystack what became of the checkout and records it. An unpaid checkout is reported as
    abandoned too, so a quote is only given up on when the person closed it or the window passed. A
    payment landing after that is kept as a refund due."""
    reference = quote.progress.get("paystackReference")
    already_paid = quote.progress.get("paymentStatus") == "success"
    if quote.state not in ("approved", "abandoned") or reference is None or already_paid:
        return PaymentCheck(quote, already_paid)
    try:
        check = await ctx.paystack.verify_transaction(reference)
    except PaystackError as error:
        raise as_domain_error(error, "confirm the payment") from error
    if check.status == "success":
        return await _settle_success(ctx, quote, check)
    if quote.state == "abandoned":
        return PaymentCheck(quote, False)
    return PaymentCheck(await _settle_stopped(ctx, quote, check, checkout_closed), False)
