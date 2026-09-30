# SPDX-License-Identifier: AGPL-3.0-or-later
"""The food-order flow, ported from the TypeScript demo's food-flow.test.ts."""

import asyncio

import pytest

from checkout.errors import DomainError
from tests.support import make_stack

_counter = 0


def quote_input(**over):
    global _counter
    _counter += 1
    return {
        "items": [("jollof-chicken", 2), ("zobo", 1)],
        "delivery_area": "Yaba",
        "note": None,
        "total_as_user_said": None,
        "idempotency_key": f"food-key-{_counter:05d}",
        **over,
    }


async def code_of(work) -> str:
    try:
        await work
    except DomainError as error:
        return error.code
    return "none"


async def paid(stack) -> str:
    issued = await stack.food.create_quote(**quote_input())
    view = await stack.food.approve(issued.quote["id"], issued.approval_token, issued.quote["amount"]["kobo"])
    await stack.complete_checkout(view["checkoutUrl"], "success")
    return issued.quote["id"]


class TestMakingAFoodQuote:
    async def test_prices_the_basket_from_the_menu_adds_delivery_and_labels_the_merchant_as_simulated(
        self, stack
    ):
        q = (await stack.food.create_quote(**quote_input())).quote
        assert q["amount"] == {"kobo": 1_100_000, "display": "₦11,000"}
        assert q["merchant"] == "Mama Put Yaba (simulated)"
        assert q["description"] == "Food order: 3 items from Mama Put Yaba (simulated)"
        d = q["details"]
        assert (d["kind"], d["area"], d["subtotal"], d["deliveryFee"]) == ("food", "Yaba", "₦9,800", "₦1,200")
        assert d["lines"] == [
            {"name": "Jollof rice with fried chicken", "quantity": 2, "unit": "₦4,500", "total": "₦9,000"},
            {"name": "Zobo, 500ml", "quantity": 1, "unit": "₦800", "total": "₦800"},
        ]
        assert q["mode"]["label"] == "Simulated merchant: not Chowdeck · Simulated: no money moves"
        assert "invented" in q["mode"]["note"]

    async def test_checks_the_expected_total_against_the_servers_and_refuses_a_difference_or_a_doubt(
        self, stack
    ):
        ok = await stack.food.create_quote(**quote_input(total_as_user_said="11k"))
        assert ok.quote["amount"]["kobo"] == 1_100_000
        assert (
            await code_of(stack.food.create_quote(**quote_input(total_as_user_said="10k")))
            == "AMOUNT_MISMATCH"
        )
        assert (
            await code_of(stack.food.create_quote(**quote_input(total_as_user_said="10k or 11k")))
            == "AMOUNT_UNCLEAR"
        )

    @pytest.mark.parametrize(
        "over",
        [{"items": [("pizza", 1)]}, {"delivery_area": "Abuja"}, {"idempotency_key": "short"}],
        ids=["an unknown item", "an area it does not serve", "a bad idempotency key"],
    )
    async def test_refuses_bad_input(self, stack, over):
        assert await code_of(stack.food.create_quote(**quote_input(**over))) == "INVALID_INPUT"

    async def test_keeps_the_delivery_area_and_item_count_not_the_note_in_the_audit_log(self, stack):
        await stack.food.create_quote(**quote_input(note="Blue gate, call on arrival"))
        log = "\n".join(stack.audit_lines)
        assert '"area": "Yaba"' in log and '"items": 3' in log
        assert "Blue gate" not in log

    async def test_returns_the_same_quote_for_the_same_key_and_refuses_the_key_for_a_different_basket(
        self, stack
    ):
        first = quote_input()
        a = await stack.food.create_quote(**first)
        assert (await stack.food.create_quote(**first)).quote["id"] == a.quote["id"]
        other = stack.food.create_quote(**{**first, "items": [("water", 1)]})
        assert await code_of(other) == "IDEMPOTENCY_CONFLICT"

    async def test_refuses_a_basket_over_the_per_payment_limit(self, stack):
        refused = stack.food.create_quote(**quote_input(items=[("catfish-pepper-soup", 10)]))
        assert await code_of(refused) == "LIMIT_PER_PAYMENT"


class TestPayingThenTheSimulatedDelivery:
    async def test_follows_the_clock_through_accepted_preparing_on_the_way_and_delivered_then_shows_a_receipt(
        self, stack
    ):
        quote_id = await paid(stack)

        async def at():
            return await stack.food.verify(quote_id)

        accepted = await at()
        assert (accepted["phase"], accepted["poll"], accepted["tracking"]["current"]) == (
            "processing",
            True,
            0,
        )
        assert "Payment received. Order accepted" in accepted["message"]
        assert accepted["tracking"]["steps"] == [
            "Order accepted",
            "Being prepared",
            "On the way",
            "Delivered",
        ]

        stack.clock.advance(15)
        assert (await at())["tracking"]["current"] == 1
        stack.clock.advance(15)
        on_the_way = await at()
        assert on_the_way["tracking"]["current"] == 2
        assert "On the way to Yaba" in on_the_way["message"]

        stack.clock.advance(15)
        done = await at()
        assert (done["phase"], done["tracking"], done["poll"]) == ("succeeded", None, False)
        assert done["receipt"]["title"] == "Order delivered"
        for line in (
            {"label": "2 \N{MULTIPLICATION SIGN} Jollof rice with fried chicken", "value": "₦9,000"},
            {"label": "Delivery", "value": "₦1,200"},
            {"label": "Total", "value": "₦11,000"},
            {"label": "Delivered to", "value": "Yaba"},
        ):
            assert line in done["receipt"]["lines"]

    async def test_places_the_order_once_however_often_it_is_checked(self, stack):
        quote_id = await paid(stack)
        await stack.food.verify(quote_id)
        placed = (await stack.ledger.get(quote_id)).progress["orderPlacedAt"]
        stack.clock.advance(20)
        await stack.food.verify(quote_id)
        await stack.food.status(quote_id)
        assert (await stack.ledger.get(quote_id)).progress["orderPlacedAt"] == placed

    async def test_places_the_order_once_however_many_check_together(self, stack):
        quote_id = await paid(stack)

        async def check(seconds):
            stack.clock.advance(seconds)
            return await stack.food.verify(quote_id)

        await asyncio.gather(*[check(1) for _ in range(12)])
        started = [line for line in stack.audit_lines if '"fulfilment.started"' in line]
        assert len(started) == 1

    async def test_does_not_start_a_kitchen_order_until_the_payment_is_confirmed(self, stack):
        issued = await stack.food.create_quote(**quote_input())
        await stack.food.approve(issued.quote["id"], issued.approval_token, issued.quote["amount"]["kobo"])
        stack.clock.advance(60)
        view = await stack.food.verify(issued.quote["id"])
        assert (view["phase"], view["tracking"]) == ("awaiting_checkout", None)
        assert "orderPlacedAt" not in (await stack.ledger.get(issued.quote["id"])).progress

    async def test_does_not_deliver_food_for_a_declined_card(self, stack):
        issued = await stack.food.create_quote(**quote_input())
        view = await stack.food.approve(
            issued.quote["id"], issued.approval_token, issued.quote["amount"]["kobo"]
        )
        await stack.complete_checkout(view["checkoutUrl"], "failed")
        assert (await stack.food.verify(issued.quote["id"]))["phase"] == "failed"

    async def test_refuses_an_approval_without_the_token_and_with_another_amount(self, stack):
        issued = await stack.food.create_quote(**quote_input())
        kobo = issued.quote["amount"]["kobo"]
        assert await code_of(stack.food.approve(issued.quote["id"], "x", kobo)) == "APPROVAL_DENIED"
        assert (
            await code_of(stack.food.approve(issued.quote["id"], issued.approval_token, 1))
            == "AMOUNT_MISMATCH"
        )

    async def test_the_kitchen_step_length_is_a_setting(self):
        from checkout.config import SimulatorSettings

        stack = make_stack(simulator=SimulatorSettings(food_step_seconds=5))
        quote_id = await paid(stack)
        await stack.food.verify(quote_id)
        stack.clock.advance(5)
        assert (await stack.food.verify(quote_id))["tracking"]["current"] == 1
