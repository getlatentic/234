# SPDX-License-Identifier: AGPL-3.0-or-later
"""The card's picture of a quote, read from the ledger, never from what the model said.

The shape is `QuoteView` of the TypeScript demo (src/contract/quote-view.ts), key for key, so its
built card reads this server's results unchanged.
"""

from datetime import UTC, datetime
from typing import Any

from .clock import Clock
from .food.tracking import ORDER_STEPS, tracking_of
from .ledger import Budget, Quote
from .mask import group_phone, mask_account
from .modes import Modes, describe_mode
from .money import format_naira
from .network import NETWORK_LABEL
from .paystack.sim import SIMULATED_OTP
from .receipts import receipt_for

WAITING = ("awaiting_checkout", "processing")

FIXED_MESSAGES = {
    "abandoned": "Checkout closed. Nothing was charged.",
    "expired": "Quote expired. Ask for a new one.",
    "declined": "Declined. Nothing was charged.",
}
REFUND_NOTE = "Refund due; this demo does not issue refunds."

PHASE_WORDS = {
    "awaiting_approval": "waiting for the person to approve it on the card",
    "awaiting_checkout": "approved; the person is completing the Paystack checkout",
    "awaiting_otp": "approved; Paystack is waiting for a one-time code from the person",
    "processing": "in progress",
    "succeeded": "succeeded",
    "attention": "paid, but the order could not be completed; a refund is due",
    "failed": "failed; nothing was charged",
    "abandoned": "abandoned; nothing was charged",
    "expired": "expired before approval",
    "declined": "declined by the person",
    "unavailable": "not possible on this account; nothing was sent or charged",
}


def _approved_phase(quote: Quote) -> str:
    progress = quote.progress
    if quote.kind == "transfer":
        return "awaiting_otp" if progress.get("transferStatus") == "otp" else "processing"
    if progress.get("paymentStatus") == "success":
        return "processing"
    return "awaiting_checkout" if progress.get("checkoutUrl") else "processing"


def phase_of(quote: Quote) -> str:
    match quote.state:
        case "open":
            return "awaiting_approval"
        case "approved":
            return _approved_phase(quote)
        case "settled":
            return "succeeded"
        case "refund_due":
            return "attention"
        case state:
            return state


def _waiting_message(quote: Quote, phase: str) -> str | None:
    if phase == "processing":
        if quote.progress.get("paymentStatus") == "success":
            return "Payment received. Confirming delivery."
        return "Working on it."
    return None


def _ended_message(quote: Quote, phase: str) -> str | None:
    progress = quote.progress
    if phase == "failed":
        reason = progress.get("failureReason") or progress.get("gatewayResponse")
        return f"{reason or 'Payment failed.'} Nothing was charged."
    if phase == "unavailable":
        return progress.get("failureReason") or "Not available on this account. Nothing was charged."
    if phase == "attention":
        reason = progress.get("failureReason") or "Paid, but the order could not be completed."
        return f"{reason} {REFUND_NOTE}"
    return None


def message_for(quote: Quote, phase: str) -> str | None:
    if phase in FIXED_MESSAGES:
        return FIXED_MESSAGES[phase]
    if phase in WAITING:
        return _waiting_message(quote, phase)
    return _ended_message(quote, phase)


SANDBOX_RULES = (
    "Sandbox: VTpass is sent 08011111111, so the order succeeds and nothing reaches this number. "
    "201000000000 stays pending."
)
SIMULATED_RULES = (
    "Simulated: any Nigerian mobile number is delivered. 201000000000 stays pending; 100000000000 fails."
)
FOOD_NOTE = "The menu, prices and delivery updates are invented."
OTP_INSTRUCTIONS = "Enter the one-time code Paystack sent."


def _details_view(quote: Quote) -> dict[str, Any]:
    d = quote.details
    match d["kind"]:
        case "transfer":
            return {
                "kind": "transfer",
                "recipientName": d["recipientName"],
                "bankName": d["bankName"],
                "accountMasked": mask_account(d["accountNumber"]),
            }
        case "airtime":
            network, phone = NETWORK_LABEL[d["network"]], group_phone(d["phone"])
            read_back = f"{format_naira(quote.amount_kobo)} {network} airtime to {phone}"
            return {"kind": "airtime", "network": network, "phone": phone, "readBack": read_back}
        case "data":
            network, phone = NETWORK_LABEL[d["network"]], group_phone(d["phone"])
            read_back = f"{d['planName']} on {network} to {phone} for {format_naira(quote.amount_kobo)}"
            return {
                "kind": "data",
                "network": network,
                "phone": phone,
                "plan": d["planName"],
                "readBack": read_back,
            }
        case "food":
            return {
                "kind": "food",
                "restaurant": d["restaurant"],
                "area": d["area"],
                "lines": [
                    {
                        "name": line["name"],
                        "quantity": line["quantity"],
                        "unit": format_naira(line["unitKobo"]),
                        "total": format_naira(line["unitKobo"] * line["quantity"]),
                    }
                    for line in d["lines"]
                ],
                "subtotal": format_naira(d["subtotalKobo"]),
                "deliveryFee": format_naira(d["deliveryFeeKobo"]),
            }
        case _:
            return {"kind": "payment"}


def _mode_note(quote: Quote, modes: Modes) -> str | None:
    if quote.kind == "food":
        return FOOD_NOTE
    if quote.kind not in ("airtime", "data") or not modes.vtpass:
        return None
    return SIMULATED_RULES if modes.vtpass == "simulated" else SANDBOX_RULES


def _otp_hint(phase: str, modes: Modes) -> str | None:
    if phase != "awaiting_otp":
        return None
    if modes.paystack == "simulated":
        return f"{OTP_INSTRUCTIONS} Simulated code: {SIMULATED_OTP}."
    return OTP_INSTRUCTIONS


def _tracking_message(quote: Quote, tracking: dict[str, Any]) -> str:
    step = ORDER_STEPS[tracking["current"]]
    where = f" to {quote.details['area']}" if tracking["current"] == ORDER_STEPS.index("On the way") else ""
    return f"Payment received. {step}{where}. Simulated: the steps follow a clock."


def present_quote(
    quote: Quote, budget: Budget, modes: Modes, clock: Clock, food_step_seconds: int = 15
) -> dict[str, Any]:
    phase = phase_of(quote)
    mode = describe_mode(modes)
    tracking = tracking_of(quote.state, quote.kind, quote.progress, clock.now(), food_step_seconds * 1000)
    return {
        "id": quote.id,
        "phase": phase,
        "amount": {"kobo": quote.amount_kobo, "display": format_naira(quote.amount_kobo)},
        "description": quote.description,
        "merchant": quote.merchant,
        "merchantRef": quote.merchant_ref,
        "expiresAt": datetime.fromtimestamp(quote.expires_at / 1000, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "mode": {"label": mode.label, "simulated": mode.simulated, "note": _mode_note(quote, modes)},
        "limits": {
            "perPayment": format_naira(budget.per_payment_kobo),
            "daily": format_naira(budget.daily_kobo),
            "remainingToday": format_naira(budget.remaining_today_kobo),
        },
        "details": _details_view(quote),
        "checkoutUrl": quote.progress.get("checkoutUrl") if phase == "awaiting_checkout" else None,
        "otpHint": _otp_hint(phase, modes),
        "tracking": tracking,
        "receipt": receipt_for(quote, mode.label),
        "message": _tracking_message(quote, tracking) if tracking else message_for(quote, phase),
        "poll": phase in WAITING,
    }


def summarise(view: dict[str, Any]) -> str:
    """What the model reads about a quote. It never holds the approval token or the checkout link."""
    what = (
        view["description"]
        if view["description"] == view["merchant"]
        else f"{view['description']} ({view['merchant']})"
    )
    lines = [
        f"Quote {view['id']}: {view['amount']['display']} for {what}.",
        f"Status: {PHASE_WORDS[view['phase']]}.",
        view["message"],
        f"Mode: {view['mode']['label']}.",
    ]
    return " ".join(line for line in lines if line)
