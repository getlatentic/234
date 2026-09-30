# SPDX-License-Identifier: AGPL-3.0-or-later
"""Send money from the Paystack balance to a bank account, against a quote the server holds.

The person approves once; the transfer starts at most once. The provider step is held by one caller at
a time, the transfer's reference is fixed by the quote, and a retry after a lost reply asks Paystack
what became of that reference before it sends anything. A refusal fails closed: no fallback to the
simulator, nothing stays reserved.
"""

import re
from typing import Any

from ..errors import DomainError
from ..ids import transfer_reference
from ..ledger import NewQuote, Quote, request_hash
from ..money import Kobo, format_naira
from ..paystack.api import (
    AccountLookup,
    PaystackError,
    RecipientRequest,
    TransferOutcome,
    TransferRequest,
    is_payouts_unavailable,
)
from .bank_choice import choose_bank
from .base import CardFlow
from .checkout_leg import STEP_STALE_MS
from .context import QuoteIssued
from .inputs import assert_idempotency_key, clean_text, confirm_stated_amount
from .provider_error import as_domain_error

PAYOUTS_UNAVAILABLE_MESSAGE = (
    "Paystack test transfers are not enabled on this account (Starter Business). Nothing was sent or "
    "charged. To continue in simulated mode, set SEND_MONEY_MODE=simulated and redeploy; the cards will "
    "then say so."
)

_ACCOUNT_NUMBER = re.compile(r"\d{10}")
_OTP = re.compile(r"\d{4,10}")


def _clean_account(account_number: str) -> str:
    account = re.sub(r"[\s-]", "", account_number)
    if not _ACCOUNT_NUMBER.fullmatch(account):
        raise DomainError("INVALID_INPUT", "account_number must be a 10 digit Nigerian bank account number.")
    return account


class TransferFlow(CardFlow):
    connector = "send-money"

    async def create_quote(
        self,
        *,
        account_number: str,
        amount_kobo: Kobo,
        amount_as_user_said: str,
        narration: str | None,
        idempotency_key: str,
        bank: str | None = None,
        bank_code: str | None = None,
    ) -> QuoteIssued:
        async def work():
            assert_idempotency_key(idempotency_key)
            account = _clean_account(account_number)
            chosen = choose_bank(bank, bank_code)
            note = clean_text(narration or "Transfer", "narration", 100)
            confirm_stated_amount(amount_kobo, amount_as_user_said)
            digest = request_hash(amount_kobo=amount_kobo, account=account, bank=chosen.code, narration=note)
            ledger = self.ctx.ledger
            replayed = await ledger.replay(self.connector, idempotency_key, digest)
            if replayed:
                return replayed, True
            await ledger.assert_quotable(amount_kobo)
            try:
                name = await self.ctx.paystack.resolve_account(AccountLookup(account, chosen.code))
                recipient = await self.ctx.paystack.create_recipient(
                    RecipientRequest(name, account, chosen.code)
                )
            except PaystackError as error:
                raise as_domain_error(error, "look up that account") from error
            return await ledger.create(
                NewQuote(
                    connector=self.connector,
                    kind="transfer",
                    amount_kobo=amount_kobo,
                    description=note,
                    merchant=name,
                    merchant_ref=None,
                    details={
                        "kind": "transfer",
                        "recipientCode": recipient.recipient_code,
                        "recipientName": name,
                        "bankCode": chosen.code,
                        "bankName": chosen.name or recipient.bank_name,
                        "accountNumber": account,
                    },
                    idempotency_key=idempotency_key,
                    request_hash=digest,
                )
            )

        return await self.make_quote(work)

    async def approve(
        self, quote_id: str, token: str, displayed_amount_kobo: Kobo, readback_confirmed: bool | None = None
    ) -> dict[str, Any]:
        quote, _ = await self.authorise_approval(quote_id, token, displayed_amount_kobo)
        return await self.present(await self._start_transfer(quote))

    async def _start_transfer(self, quote: Quote) -> Quote:
        """Sends the transfer unless it already went, or another caller is sending it now."""
        ledger = self.ctx.ledger
        fresh = await ledger.get(quote.id)
        if fresh is None or fresh.state != "approved" or "transferStatus" in fresh.progress:
            return fresh or quote
        if not await ledger.acquire_step(quote.id, STEP_STALE_MS, {"transferAttempted": True}):
            return fresh
        try:
            outcome = await self._send_or_find(fresh)
        except PaystackError as error:
            return await self._settle_refusal(fresh, error)
        except Exception:
            await ledger.patch_progress(quote.id, {"inFlightSince": None})
            raise
        self.ctx.audit.log("transfer.started", quote=quote.id, status=outcome.status)
        return await self._record(fresh, outcome)

    async def _send_or_find(self, quote: Quote) -> TransferOutcome:
        """An earlier attempt may have reached Paystack: ask about its reference before sending again."""
        reference = transfer_reference(quote.id)
        if quote.progress.get("transferAttempted"):
            try:
                return await self.ctx.paystack.verify_transfer(reference)
            except PaystackError as error:
                if error.retryable:
                    raise
        d = quote.details
        request = TransferRequest(quote.amount_kobo, d["recipientCode"], reference, quote.description)
        return await self.ctx.paystack.initiate_transfer(request)

    async def _settle_refusal(self, quote: Quote, error: PaystackError) -> Quote:
        ledger, audit = self.ctx.ledger, self.ctx.audit
        if is_payouts_unavailable(error):
            audit.log("transfer.failed", quote=quote.id, why="payouts unavailable on this account")
            return await ledger.transition(
                quote.id,
                ("approved",),
                "unavailable",
                {"failureReason": PAYOUTS_UNAVAILABLE_MESSAGE, "inFlightSince": None},
            )
        if not error.retryable:
            audit.log("transfer.failed", quote=quote.id, why="refused by Paystack")
            return await ledger.transition(
                quote.id, ("approved",), "failed", {"failureReason": str(error), "inFlightSince": None}
            )
        await ledger.patch_progress(quote.id, {"inFlightSince": None})
        raise as_domain_error(error, "send the transfer") from error

    async def _record(self, quote: Quote, outcome: TransferOutcome) -> Quote:
        """Writes what Paystack said and lets go of the provider step, only while the quote is approved."""
        ledger, audit = self.ctx.ledger, self.ctx.audit
        seen: dict[str, Any] = {
            "transferReference": outcome.reference,
            "transferCode": outcome.transfer_code,
            "transferStatus": outcome.status,
            "inFlightSince": None,
        }
        try:
            if outcome.amount_kobo != quote.amount_kobo:
                reason = (
                    f"Paystack reported a transfer of {format_naira(outcome.amount_kobo)} "
                    f"for a {format_naira(quote.amount_kobo)} quote."
                )
                audit.log("refund.due", quote=quote.id, why=reason)
                return await ledger.transition(
                    quote.id, ("approved",), "refund_due", {**seen, "failureReason": reason}
                )
            match outcome.status:
                case "success":
                    audit.log("transfer.settled", quote=quote.id, amount_kobo=quote.amount_kobo)
                    return await ledger.transition(quote.id, ("approved",), "settled", seen)
                case "failed" | "reversed":
                    audit.log("transfer.failed", quote=quote.id, status=outcome.status)
                    reason = (
                        "Paystack reversed the transfer."
                        if outcome.status == "reversed"
                        else "Paystack reported the transfer as failed."
                    )
                    return await ledger.transition(
                        quote.id, ("approved",), "failed", {**seen, "failureReason": reason}
                    )
                case status:
                    if status == "otp":
                        audit.log("transfer.otp_required", quote=quote.id)
                    return await ledger.patch_progress(quote.id, seen, only_state="approved")
        except DomainError:
            return await ledger.require(quote.id, self.connector)

    async def submit_otp(self, quote_id: str, otp: str) -> dict[str, Any]:
        """The one-time code Paystack asks for when transfers need confirming. It is passed on and never
        stored or logged."""
        ledger = self.ctx.ledger
        quote = await ledger.require(quote_id, self.connector)
        code = quote.progress.get("transferCode")
        if quote.state != "approved" or quote.progress.get("transferStatus") != "otp" or code is None:
            raise DomainError("NOT_VERIFIABLE", "This transfer is not waiting for a one-time code.")
        if not _OTP.fullmatch(otp):
            raise DomainError("INVALID_INPUT", "The one-time code is 4 to 10 digits.")
        if not await ledger.acquire_step(quote.id, STEP_STALE_MS):
            raise DomainError("APPROVAL_IN_PROGRESS", "A code is already being checked. Wait a moment.")
        try:
            outcome = await self.ctx.paystack.finalize_transfer(code, otp)
        except PaystackError as error:
            await ledger.patch_progress(quote.id, {"inFlightSince": None})
            if not error.retryable:
                raise DomainError(
                    "OTP_REJECTED", f"Paystack did not accept that code: {error}. Check it and try again."
                ) from error
            raise as_domain_error(error, "confirm the code") from error
        return await self.present(await self._record(quote, outcome))

    async def verify(self, quote_id: str, checkout_closed: bool = False) -> dict[str, Any]:
        ledger = self.ctx.ledger
        quote = await ledger.require(quote_id, self.connector)
        status = quote.progress.get("transferStatus")
        if quote.state != "approved" or status not in (None, "pending"):
            return await self.present(quote)
        if status is None:
            return await self.present(await self._start_transfer(quote))
        try:
            outcome = await self.ctx.paystack.verify_transfer(quote.progress["transferReference"])
        except PaystackError as error:
            raise as_domain_error(error, "confirm the transfer") from error
        return await self.present(await self._record(quote, outcome))
