# SPDX-License-Identifier: AGPL-3.0-or-later
"""A simulated merchant: the menu, prices and delivery are invented, but the payment leg is the real
shared one. After payment the kitchen is a clock: the order is handed over once, and its steps follow
the time until it reads delivered."""

from typing import Any

from ..food.menu import RESTAURANT, PricedBasket, assert_delivery_area, price_basket
from ..food.tracking import LAST_STEP, step_of
from ..ledger import NewQuote, Quote, request_hash
from ..money import Kobo
from .base import CardFlow
from .checkout_leg import begin_checkout, check_payment
from .context import QuoteIssued
from .inputs import assert_idempotency_key, clean_text, confirm_stated_amount


class FoodFlow(CardFlow):
    connector = "food-order"

    async def create_quote(
        self,
        *,
        items: list[tuple[str, int]],
        delivery_area: str,
        note: str | None,
        total_as_user_said: str | None,
        idempotency_key: str,
    ) -> QuoteIssued:
        async def work():
            assert_idempotency_key(idempotency_key)
            basket = price_basket(items)
            area = assert_delivery_area(delivery_area)
            text = None if note is None else clean_text(note, "note", 120)
            if total_as_user_said is not None:
                confirm_stated_amount(basket.total_kobo, total_as_user_said)
            return await self.ctx.ledger.create(self._new_quote(basket, area, text, idempotency_key))

        return await self.make_quote(work)

    def _new_quote(self, basket: PricedBasket, area: str, note: str | None, idempotency_key: str) -> NewQuote:
        count = sum(line.quantity for line in basket.lines)
        lines = [line.as_detail() for line in basket.lines]
        return NewQuote(
            connector=self.connector,
            kind="food",
            amount_kobo=basket.total_kobo,
            description=f"Food order: {count} item{'' if count == 1 else 's'} from {RESTAURANT}",
            merchant=RESTAURANT,
            merchant_ref=None,
            details={
                "kind": "food",
                "restaurant": RESTAURANT,
                "area": area,
                "note": note,
                "lines": lines,
                "subtotalKobo": basket.subtotal_kobo,
                "deliveryFeeKobo": basket.delivery_fee_kobo,
            },
            idempotency_key=idempotency_key,
            request_hash=request_hash(lines=lines, area=area, note=note),
        )

    async def approve(
        self, quote_id: str, token: str, displayed_amount_kobo: Kobo, readback_confirmed: bool | None = None
    ) -> dict[str, Any]:
        quote, _ = await self.authorise_approval(quote_id, token, displayed_amount_kobo)
        return await self.present(await begin_checkout(self.ctx, quote))

    async def verify(self, quote_id: str, checkout_closed: bool = False) -> dict[str, Any]:
        quote = await self.ctx.ledger.require(quote_id, self.connector)
        checked = await check_payment(self.ctx, quote, checkout_closed)
        if not checked.paid or checked.quote.state != "approved":
            return await self.present(checked.quote)
        return await self.present(await self._advance(checked.quote))

    async def _advance(self, paid: Quote) -> Quote:
        """Hands a paid order to the kitchen once, then delivers it when the clock says so."""
        ledger, clock = self.ctx.ledger, self.ctx.clock
        quote = paid if paid.progress.get("orderPlacedAt") is not None else await self._place(paid)
        step = step_of(quote.progress.get("orderPlacedAt"), clock.now(), self.ctx.food_step_seconds * 1000)
        if step != LAST_STEP:
            return quote
        self.ctx.audit.log("fulfilment.delivered", quote=quote.id)
        return await ledger.transition(quote.id, ("approved",), "settled")

    async def _place(self, paid: Quote) -> Quote:
        """The first caller writes the hand-over time; a racing caller keeps it."""
        ledger = self.ctx.ledger
        if await ledger.set_progress_once(paid.id, "orderPlacedAt", self.ctx.clock.now()):
            self.ctx.audit.log("fulfilment.started", quote=paid.id)
        return await ledger.require(paid.id, self.connector)
