# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Paystack checks: initialize, verify, a repeated reference, the transfer path, and a real payment."""

import asyncio
import os
import time

from checkout.paystack.api import (
    AccountLookup,
    CheckoutRequest,
    PaystackApi,
    PaystackError,
    RecipientRequest,
    TransferOutcome,
    TransferRequest,
    is_payouts_unavailable,
)
from tools.live_report import Report

TEST_AMOUNT_KOBO = 5_000
ACCOUNT = AccountLookup("0000000000", "057")
PAY_WAIT_SECONDS = 300


def stamp() -> str:
    return f"{int(time.time() * 1000)}{os.urandom(3).hex()}"


async def _duplicate_result(paystack: PaystackApi, request: CheckoutRequest) -> str:
    try:
        await paystack.initialize_transaction(request)
    except PaystackError as error:
        return str(error)
    return "accepted"


async def paystack_checks(
    paystack: PaystackApi, report: Report, *, real_host: bool, email: str, transfer: bool, pay: bool
) -> None:
    reference = f"livecheck-{stamp()}"
    request = CheckoutRequest(TEST_AMOUNT_KOBO, email, reference, "livecheck", "live-check")

    def on_paystack(checkout) -> str | None:
        ok = not real_host or checkout.authorization_url.startswith("https://checkout.paystack.com/")
        return None if ok else "authorization_url is not on checkout.paystack.com"

    started = await report.check(
        "initialize a transaction", lambda: paystack.initialize_transaction(request), on_paystack
    )
    unpaid = await report.check(
        "verify an unpaid transaction (amount and currency intact)",
        lambda: paystack.verify_transaction(reference),
        lambda v: (
            None
            if (v.amount_kobo, v.currency) == (TEST_AMOUNT_KOBO, "NGN")
            else f"amount {v.amount_kobo} {v.currency}"
        ),
    )
    if unpaid:
        report.note(
            "unpaid status",
            f"{unpaid.status} (the code treats abandoned, ongoing and pending as still waiting)",
        )
    again = await report.check(
        "a repeated reference is refused",
        lambda: _duplicate_result(paystack, request),
        lambda r: "the duplicate was accepted" if r == "accepted" else None,
    )
    if again:
        report.note("duplicate reference", again)
    if transfer:
        await transfer_checks(paystack, report)
    if pay and started:
        await pay_check(paystack, report, reference, started.authorization_url)


async def transfer_checks(paystack: PaystackApi, report: Report) -> None:
    report.say("\nTransfers (Paystack's documented test account: 0000000000 at Zenith Bank, code 057)")
    name = await report.check(
        "resolve the test account",
        lambda: paystack.resolve_account(ACCOUNT),
        lambda n: None if n else "no name",
    )
    if not name:
        return
    report.note("account name", name)
    recipient = await report.check(
        "create a transfer recipient",
        lambda: paystack.create_recipient(RecipientRequest(name, ACCOUNT.account_number, ACCOUNT.bank_code)),
        lambda r: None if r.recipient_code.startswith("RCP_") else "no recipient code",
    )
    if not recipient:
        return
    reference = f"livecheck-trf-{stamp()}".lower()
    request = TransferRequest(10_000, recipient.recipient_code, reference, "live-check")
    sent = await initiate(paystack, report, request)
    if sent is None:
        return
    if sent.status == "otp":
        report.note(
            "OTP is ON",
            "Paystack asked for an OTP. Turn it off in the test dashboard (Settings, Preferences, uncheck "
            '"Confirm transfers before sending"), or finish the transfer with the OTP Paystack sends.',
        )
        return
    report.note("transfer status", f"{sent.status} (Paystack says test transfers always return success)")
    await report.check(
        "verify the transfer by reference",
        lambda: paystack.verify_transfer(reference),
        lambda t: None if t.transfer_code == sent.transfer_code else "a different transfer came back",
    )
    await report.check(
        "repeat the same transfer reference (retry safety)",
        lambda: paystack.initiate_transfer(request),
        lambda t: None if t.transfer_code == sent.transfer_code else "a second transfer was made",
    )


async def initiate(paystack: PaystackApi, report: Report, request: TransferRequest) -> TransferOutcome | None:
    """A Starter Business account is refused payouts even in test mode, which is a note, not a failure."""
    try:
        sent = await paystack.initiate_transfer(request)
    except PaystackError as error:
        if is_payouts_unavailable(error):
            report.note(
                "payouts unavailable on this account",
                "Paystack refused the transfer (Starter Business). Transfers stay simulated until the "
                "business "
                "is registered; set SEND_MONEY_MODE=simulated. The remaining transfer steps are skipped.",
            )
        else:
            report.failure("initiate a ₦100 transfer", str(error))
        return None
    if sent.status in ("success", "pending", "otp"):
        report.passed("initiate a ₦100 transfer")
    else:
        report.failure("initiate a ₦100 transfer", f"status {sent.status}")
    return sent


async def pay_check(paystack: PaystackApi, report: Report, reference: str, url: str) -> None:
    report.say(
        "\nOpen this Paystack test checkout and pay with the published test card "
        "4084 0840 8408 4081, any future expiry, CVV 408:"
    )
    report.say(url)
    deadline = time.time() + PAY_WAIT_SECONDS
    while time.time() < deadline:
        check = await paystack.verify_transaction(reference)
        if check.status == "success":
            matches = (check.amount_kobo, check.currency) == (TEST_AMOUNT_KOBO, "NGN")
            if matches:
                report.passed("the test payment succeeded", "amount and currency match")
            else:
                report.failure("the test payment succeeded", "amount or currency differs")
            return
        if check.status == "failed":
            report.failure("the test payment", "failed")
            return
        await asyncio.sleep(3)
    report.failure("the test payment", "not completed within 5 minutes")
