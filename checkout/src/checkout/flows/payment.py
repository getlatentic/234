# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pay a merchant through Paystack's hosted checkout, against a quote the server holds."""

from typing import Any

from ..ledger import NewQuote, request_hash
from ..money import Kobo
from .base import CardFlow
from .checkout_leg import begin_checkout, check_payment
from .context import QuoteIssued
from .inputs import assert_idempotency_key, clean_reference, clean_text, confirm_stated_amount


class PaymentFlow(CardFlow):
    connector = "paystack-pay"

    async def create_quote(
        self,
        *,
        amount_kobo: Kobo,
        amount_as_user_said: str,
        description: str,
        merchant: str,
        merchant_ref: str | None,
        idempotency_key: str,
    ) -> QuoteIssued:
        async def work():
            assert_idempotency_key(idempotency_key)
            text = clean_text(description, "description", 140)
            name = clean_text(merchant, "merchant", 60)
            reference = clean_reference(merchant_ref)
            confirm_stated_amount(amount_kobo, amount_as_user_said)
            return await self.ctx.ledger.create(
                NewQuote(
                    connector=self.connector,
                    kind="payment",
                    amount_kobo=amount_kobo,
                    description=text,
                    merchant=name,
                    merchant_ref=reference,
                    details={"kind": "payment"},
                    idempotency_key=idempotency_key,
                    request_hash=request_hash(
                        amount_kobo=amount_kobo, description=text, merchant=name, merchant_ref=reference
                    ),
                )
            )

        return await self.make_quote(work)

    async def approve(
        self, quote_id: str, token: str, displayed_amount_kobo: Kobo, readback_confirmed: bool | None = None
    ) -> dict[str, Any]:
        quote, _ = await self.authorise_approval(quote_id, token, displayed_amount_kobo)
        return await self.present(await begin_checkout(self.ctx, quote))

    async def verify(self, quote_id: str, checkout_closed: bool = False) -> dict[str, Any]:
        ledger = self.ctx.ledger
        quote = await ledger.require(quote_id, self.connector)
        checked = await check_payment(self.ctx, quote, checkout_closed)
        if not checked.paid or checked.quote.state != "approved":
            return await self.present(checked.quote)
        settled = await ledger.transition(quote.id, ("approved",), "settled")
        self.ctx.audit.log("payment.settled", quote=quote.id, amount_kobo=quote.amount_kobo)
        return await self.present(settled)
