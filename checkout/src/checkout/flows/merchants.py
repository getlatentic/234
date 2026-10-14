# SPDX-License-Identifier: AGPL-3.0-or-later
"""Buying from a merchant of the directory (docs/commerce.md). The quote is made for a merchant id the
directory lists, priced by that merchant's provider from its offers alone, and carries the holder's name
where the provider checked an account. The person's approval is bound to a digest of all of it
(commerce/binding.py); paid, from the wallet or at Paystack's checkout, the order goes to the provider
(merchant_leg.py)."""

from collections.abc import Mapping
from typing import Any

from ..commerce.binding import approval_subject
from ..commerce.fields import buyer_fields
from ..commerce.index.tokens import not_connected
from ..commerce.model import Basket, BasketLine, Merchant, Totals
from ..commerce.pricing import merged
from ..commerce.quote_details import describe, details_of, is_external
from ..errors import DomainError
from ..ledger import ClaimTerms, NewQuote, Quote, request_hash
from ..money import Kobo
from .base import CardFlow
from .checkout_leg import begin_checkout, check_payment
from .context import Context, QuoteIssued
from .inputs import assert_idempotency_key, confirm_stated_amount
from .merchant_leg import CONNECTOR, deliver
from .wallet_leg import refund_to_wallet, wallet_of

EXTERNAL_PAID = ClaimTerms(
    {"funding": "external", "paymentStatus": "success"},
    "json_extract(quotes.details, '$.funding') = 'external'",
)


class MerchantsFlow(CardFlow):
    connector = CONNECTOR

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        if ctx.providers is None or ctx.checks is None:
            raise ValueError("The merchants connector needs the directory's providers and account checks.")
        self.providers, self.checks = ctx.providers, ctx.checks

    def approval_token_of(self, quote: Quote) -> str:
        return self.ctx.ledger.approval_token(approval_subject(quote))

    async def token_is_valid(self, quote_id: str, token: str) -> bool:
        quote = await self.ctx.ledger.get(quote_id)
        return quote is not None and self.ctx.ledger.check_approval_token(approval_subject(quote), token)

    async def create_quote(
        self,
        *,
        merchant_id: str,
        lines: tuple[BasketLine, ...],
        amount_kobo: Kobo | None,
        amount_as_user_said: str | None,
        fields: Mapping[str, str],
        check_id: str | None,
        idempotency_key: str,
    ) -> QuoteIssued:
        async def work():
            assert_idempotency_key(idempotency_key)
            merchant = await self.providers.merchant(merchant_id)
            buyer = buyer_fields(merchant, fields)
            named = lines or await self._the_offer_paid_for_an_amount(merchant, amount_kobo)
            basket = Basket(merged(named), amount_kobo, {name: value for name, _, value in buyer})
            check_id_used = check_id if merchant.checks_account else None
            digest = _digest(merchant, basket, check_id_used)
            replayed = await self.ctx.ledger.replay(self.connector, idempotency_key, digest)
            if replayed:
                return replayed, True
            _assert_quotable(merchant)
            _assert_amount_stated(amount_kobo, amount_as_user_said)
            totals = await self._priced(merchant, basket, check_id_used)
            return await self.ctx.ledger.create(_new_quote(merchant, totals, idempotency_key, digest))

        return await self.make_quote(work)

    async def _the_offer_paid_for_an_amount(
        self, merchant: Merchant, amount_kobo: Kobo | None
    ) -> tuple[BasketLine, ...]:
        """An amount without lines is for the merchant's one offer paid for any amount (docs/commerce.md:
        `lines or amount`); a merchant with none or several needs the offer named."""
        if amount_kobo is None:
            raise DomainError("INVALID_INPUT", "Pass lines: the offers and how many of each.")
        offers = await self.providers.of(merchant).offers(merchant)
        open_offers = [o for o in offers if o.price_kind == "open" and o.available]
        if len(open_offers) != 1:
            raise DomainError(
                "INVALID_INPUT",
                f"{merchant.name} has no single offer paid for any amount. Pass lines naming the offer.",
            )
        return (BasketLine(open_offers[0].id),)

    async def _priced(self, merchant: Merchant, basket: Basket, check_id: str | None) -> Totals:
        check = None
        if merchant.checks_account:
            check = await self.checks.require(check_id, merchant, basket.fields)
        return await self.providers.of(merchant).price(merchant, basket, check)

    async def approve(
        self,
        quote_id: str,
        token: str,
        displayed_amount_kobo: Kobo,
        readback_confirmed: bool | None = None,
        funding: str = "checkout",
    ) -> dict[str, Any]:
        await self._assert_funding_is_the_quotes(quote_id, funding)
        if funding == "wallet":
            await self.authorise_approval(quote_id, token, displayed_amount_kobo, wallet_of(self.ctx))
            return await self.verify(quote_id)
        quote, _ = await self.authorise_approval(quote_id, token, displayed_amount_kobo)
        return await self.present(await begin_checkout(self.ctx, quote))

    async def approve_external(
        self, quote_id: str, token: str, displayed_amount_kobo: Kobo, readback_confirmed: bool | None = None
    ) -> dict[str, Any]:
        """The person's own account at the provider pays: the approval is the quote's one claim, and the
        provider is then asked to place the order (merchant_leg.py), once."""
        await self._assert_funding_is_the_quotes(quote_id, "external")
        if self.ctx.index is not None and not await self.ctx.index.provider.connected():
            raise not_connected()
        await self.authorise_approval(quote_id, token, displayed_amount_kobo, terms=EXTERNAL_PAID)
        return await self.verify(quote_id)

    async def _assert_funding_is_the_quotes(self, quote_id: str, funding: str) -> None:
        """A quote paid from the person's own account at the provider is approved as that and no other way, and
        no other quote is: otherwise the wallet or the checkout could be charged for an order the provider also
        charges, or the provider asked to place an order nobody paid for."""
        quote = await self.ctx.ledger.require(quote_id, self.connector)
        if (funding == "external") != is_external(quote):
            audit_why = "external" if is_external(quote) else funding
            self.ctx.audit.log("approval.denied", quote=quote_id, why=f"funding {audit_why}")
            raise DomainError(
                "FUNDING_MISMATCH",
                "This quote is paid from the person's own account at the provider, and is approved on its "
                "card as that. Nothing was approved."
                if is_external(quote)
                else "This quote is not paid from an account at the provider. Nothing was approved.",
            )

    async def approve_from_wallet(
        self, quote_id: str, token: str, displayed_amount_kobo: Kobo, readback_confirmed: bool | None = None
    ) -> dict[str, Any]:
        return await self.approve(quote_id, token, displayed_amount_kobo, readback_confirmed, "wallet")

    async def verify(self, quote_id: str, checkout_closed: bool = False) -> dict[str, Any]:
        quote = await self.ctx.ledger.require(quote_id, self.connector)
        checked = await check_payment(self.ctx, quote, checkout_closed)
        quote = checked.quote
        if checked.paid and quote.state == "approved":
            quote = await deliver(self.ctx, self.providers, quote)
        return await self.present(await refund_to_wallet(self.ctx, quote))


def _assert_quotable(merchant: Merchant) -> None:
    if merchant.requires_link:
        raise DomainError(
            "LINK_REQUIRED",
            f"{merchant.name} needs the person to connect their account first. Call connect_account for "
            "it: its card is where they connect, and nothing about it goes through the chat. Nothing was "
            "quoted.",
        )
    if not merchant.quotable:
        raise DomainError(
            "MERCHANT_NOT_AVAILABLE",
            f"{merchant.name} is {merchant.status.replace('_', ' ')}: nothing can be bought from it yet.",
        )


def _assert_amount_stated(amount_kobo: Kobo | None, as_user_said: str | None) -> None:
    if amount_kobo is None:
        return
    if not as_user_said:
        raise DomainError(
            "AMOUNT_UNCLEAR",
            "Pass amount_as_user_said: the amount exactly as the person said it. It is checked against "
            "amount_kobo.",
        )
    confirm_stated_amount(amount_kobo, as_user_said)


def _digest(merchant: Merchant, basket: Basket, check_id: str | None) -> str:
    return request_hash(
        merchant=merchant.id,
        lines=sorted((line.offer_id, line.quantity, list(line.options)) for line in basket.lines),
        amount_kobo=basket.amount_kobo,
        fields=sorted(basket.fields.items()),
        check_id=check_id,
    )


def _new_quote(merchant: Merchant, totals: Totals, idempotency_key: str, digest: str) -> NewQuote:
    return NewQuote(
        connector=CONNECTOR,
        kind="basket",
        amount_kobo=totals.total_kobo,
        description=describe(totals),
        merchant=merchant.name,
        merchant_ref=None,
        details=details_of(merchant, totals),
        idempotency_key=idempotency_key,
        request_hash=digest,
    )
