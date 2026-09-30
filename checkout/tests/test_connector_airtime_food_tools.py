# SPDX-License-Identifier: AGPL-3.0-or-later
"""The airtime and food-order tools through JSON-RPC, ported from the TypeScript demo's connector tests."""

from checkout.config import SimulatorSettings
from tests.connector_support import approve_args, key, quote_of, text_of
from tests.support import make_stack


class TestAirtimeTools:
    def airtime_args(self, **over):
        return {
            "network": "mtn",
            "phone": "08011111111",
            "amount_kobo": 50_000,
            "amount_as_user_said": "₦500",
            "idempotency_key": key("mcp-airtime"),
            **over,
        }

    async def test_tells_the_model_to_read_the_number_and_amount_back(self, stack):
        made = await stack.call("airtime", "create_airtime_quote", **self.airtime_args())
        assert (
            'Read this back to the person before they approve: "₦500 MTN airtime to 0801 111 1111"'
            in text_of(made)
        )
        details = quote_of(made)["details"]
        assert (details["kind"], details["network"], details["phone"]) == ("airtime", "MTN", "0801 111 1111")

    async def test_will_not_approve_without_the_persons_read_back_confirmation(self, stack):
        made = await stack.call("airtime", "create_airtime_quote", **self.airtime_args())
        assert text_of(await stack.call("airtime", "approve_quote", **approve_args(made))).startswith(
            "READBACK_REQUIRED"
        )
        ok = await stack.call("airtime", "approve_quote", **approve_args(made, readback_confirmed=True))
        assert quote_of(ok)["phase"] == "awaiting_checkout"

    async def test_pays_through_paystack_then_delivers_and_shows_a_receipt(self, stack):
        made = await stack.call("airtime", "create_airtime_quote", **self.airtime_args())
        approved = await stack.call("airtime", "approve_quote", **approve_args(made, readback_confirmed=True))
        await stack.complete_checkout(quote_of(approved)["checkoutUrl"], "success")
        done = await stack.call("airtime", "verify_quote", quote_id=quote_of(made)["id"])
        assert (quote_of(done)["phase"], quote_of(done)["receipt"]["title"]) == (
            "succeeded",
            "Airtime delivered",
        )

    async def test_lists_data_plans_and_quotes_one_at_the_plans_price(self, stack):
        plans = await stack.call("airtime", "list_data_plans", network="mtn")
        assert "mtn-10mb-100: N100 100MB - 24 hrs, ₦100" in text_of(plans)
        assert plans["structuredContent"]["plans"][0] == {
            "code": "mtn-10mb-100", "name": "N100 100MB - 24 hrs", "amountKobo": 10_000, "price": "₦100",
        }  # fmt: skip
        made = await stack.call(
            "airtime", "create_data_quote", network="mtn", phone="08011111111",
            plan_code="mtn-100mb-1000", idempotency_key="mcp-data-00001",
        )  # fmt: skip
        assert quote_of(made)["amount"]["display"] == "₦1,000"
        assert "N1000 1.5GB - 30 days on MTN to 0801 111 1111 for ₦1,000" in text_of(made)

    async def test_refuses_an_unknown_network(self, stack):
        result = await stack.call("airtime", "create_airtime_quote", **self.airtime_args(network="vodafone"))
        assert result["isError"] is True

    async def test_an_unreachable_vtpass_is_a_plain_refusal_not_a_server_error(self):
        stack = make_stack(simulator=SimulatorSettings(vtpass_rejects_credentials=True))
        result = await stack.call("airtime", "create_airtime_quote", **self.airtime_args())
        assert text_of(result).startswith("PROVIDER_ERROR") and "nothing was quoted" in text_of(result)


class TestFoodTools:
    def quote_args(self, **over):
        return {
            "items": [{"item_id": "beef-suya", "quantity": 1}, {"item_id": "chapman", "quantity": 2}],
            "delivery_area": "Surulere",
            "idempotency_key": key("mcp-food"),
            **over,
        }

    async def test_gives_the_model_no_way_to_set_a_price(self, stack):
        sneaky = await stack.call(
            "food-order", "create_food_quote",
            **self.quote_args(items=[{"item_id": "beef-suya", "quantity": 1, "price": 1}]),
        )  # fmt: skip
        assert sneaky["isError"] is True

    async def test_prices_a_basket_without_making_an_order(self, stack):
        basket = await stack.call(
            "food-order", "build_basket", items=[{"item_id": "beef-suya", "quantity": 2}]
        )
        assert "Total: ₦8,200" in text_of(basket)
        assert "quote" not in basket["structuredContent"]
        unknown = await stack.call("food-order", "build_basket", items=[{"item_id": "pizza", "quantity": 1}])
        assert text_of(unknown).startswith("INVALID_INPUT")
        assert await stack.count("quotes") == 0

    async def test_shows_the_card_with_the_mode_and_runs_the_order_to_delivery(self, stack):
        made = await stack.call("food-order", "create_food_quote", **self.quote_args())
        quote = quote_of(made)
        assert quote["mode"]["label"] == "Simulated merchant: not Chowdeck · Simulated: no money moves"
        assert "get_quote_status on the food-order connector" in text_of(made)
        approved = await stack.call("food-order", "approve_quote", **approve_args(made))
        await stack.complete_checkout(quote_of(approved)["checkoutUrl"], "success")
        tracking = quote_of(await stack.call("food-order", "verify_quote", quote_id=quote["id"]))["tracking"]
        assert tracking["current"] == 0
        stack.clock.advance(46)
        done = quote_of(await stack.call("food-order", "verify_quote", quote_id=quote["id"]))
        assert (done["phase"], done["receipt"]["title"]) == ("succeeded", "Order delivered")

    async def test_refuses_a_delivery_area_it_does_not_serve(self, stack):
        result = await stack.call("food-order", "create_food_quote", **self.quote_args(delivery_area="Abuja"))
        assert result["isError"] is True
