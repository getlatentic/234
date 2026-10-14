# SPDX-License-Identifier: AGPL-3.0-or-later
"""Quotes for Index merchants: Index's own previews put its breakdown on 234's card, the amounts are bounded
by Index's limits, 234's caps and the daily limit before Index is asked, a person whose Zap cannot pay is
told so before a quote exists, and nothing is charged by making one."""

import pytest

from checkout.commerce.index.settings import IndexSettings
from tests.commerce_support import fund
from tests.index_support import (
    CHOWDECK,
    IKEJA,
    METER,
    OTHER_METER,
    account,
    airtime,
    calls,
    connect,
    electricity,
    electricity_check,
    link_chowdeck,
    new_key,
    ok,
    quote,
    set_account,
    text_of,
    tools_called,
    visitor,
)
from tests.support import ALICE, make_stack


async def refused(stack, **request):
    result = await account(stack, "create_quote", **request)
    assert result.get("isError"), "the quote was made"
    return text_of(result)


async def untouched(stack):
    assert await stack.count("quotes") == 0
    assert await stack.count("sim_index_order") == 0


class TestAirtime:
    async def test_the_card_shows_whose_money_pays_and_what_is_left(self, stack):
        await connect(stack)
        made = await quote(stack)
        view = made["structuredContent"]["quote"]
        assert view["amount"]["display"] == "₦1,000"
        assert view["details"]["paidFrom"] == "your Zap balance at Paystack Index"
        assert view["details"]["balanceAfter"] == "₦49,000"
        assert [(f["label"], f["value"]) for f in view["details"]["fields"]] == [
            ("Phone number", "0803 123 4567")
        ]
        assert (
            view["mode"]["label"] == "Simulated Paystack Index: no money moves"
            and view["phase"] == "awaiting_approval"
        )

    async def test_the_model_is_told_the_person_pays_from_their_zap_and_the_wallet_is_not_used(self, stack):
        await connect(stack)
        told = text_of(await quote(stack))
        assert "pays this from your Zap balance at Paystack Index" in told and "wallet is not used" in told
        assert "Nothing is ordered or paid until the person approves" in told

    async def test_the_card_offers_no_wallet_even_to_a_funded_account(self, stack):
        await connect(stack)
        await fund(stack, 5_000_000, ALICE)
        made = await quote(stack, **airtime(from_wallet=True))
        assert "wallet" not in made["structuredContent"]["quote"]
        assert "does NOT cover" not in text_of(made) and "Pay from wallet" not in text_of(made)

    async def test_making_the_quote_only_looks(self, stack):
        await connect(stack)
        before = await set_zap(stack)
        await quote(stack)
        assert await tools_called(stack) == ["browse_merchants", "get_balance"]
        assert await stack.count("sim_index_order") == 0 and await set_zap(stack) == before

    async def test_a_phone_in_international_form_is_read_as_the_same_number(self, stack):
        await connect(stack)
        made = await quote(stack, **airtime(fields={"phone": "+234 803 123 4567"}))
        assert made["structuredContent"]["quote"]["details"]["fields"][0]["value"] == "0803 123 4567"

    async def test_a_number_that_is_not_nigerian_is_refused_before_index_is_asked(self, stack):
        await connect(stack)
        assert "INVALID_INPUT" in await refused(stack, **airtime(fields={"phone": "12345678901"}))
        assert "get_balance" not in await tools_called(stack)

    async def test_the_model_cannot_name_a_price_the_person_did_not_say(self, stack):
        await connect(stack)
        assert "AMOUNT" in await refused(stack, **airtime(amount_as_user_said="500 naira"))
        assert "AMOUNT_REQUIRED" in await refused(
            stack, **airtime(amount_kobo=None, amount_as_user_said=None)
        )
        await untouched(stack)

    async def test_the_same_request_again_is_the_same_quote(self, stack):
        await connect(stack)
        request = airtime()
        first, second = await quote(stack, **request), await quote(stack, **request)
        assert first["structuredContent"]["quote"]["id"] == second["structuredContent"]["quote"]["id"]
        assert await stack.count("quotes") == 1

    async def test_an_amount_with_kobo_is_refused_because_index_takes_naira(self, stack):
        await connect(stack)
        assert "whole naira" in await refused(
            stack, **airtime(amount_kobo=100_050, amount_as_user_said="1000.50")
        )


class TestTheLimits:
    @pytest.mark.parametrize(("kobo", "said"), [(4_900, "49 naira"), (500_100, "5001 naira")])
    async def test_below_or_above_indexs_airtime_bounds_is_refused_before_index_is_asked(
        self, stack, kobo, said
    ):
        await connect(stack)
        text = await refused(stack, **airtime(amount_kobo=kobo, amount_as_user_said=said))
        assert "AMOUNT_" in text and "get_balance" not in await tools_called(stack)

    async def test_234s_cap_for_the_kind_is_below_indexs(self):
        stack = make_stack(
            index=IndexSettings(caps_kobo={"airtime": 300_000, "electricity": 5_000_000, "food": 2_000_000})
        )
        await connect(stack)
        assert "takes ₦50 to ₦3,000" in await refused(
            stack, **airtime(amount_kobo=350_000, amount_as_user_said="3500 naira")
        )
        assert "get_balance" not in await tools_called(stack)
        ok(
            await account(
                stack, "create_quote", **airtime(amount_kobo=300_000, amount_as_user_said="3000 naira")
            )
        )

    async def test_electricity_has_its_own_bounds_under_234s_cap(self):
        stack = make_stack(
            index=IndexSettings(caps_kobo={"airtime": 500_000, "electricity": 3_000_000, "food": 2_000_000})
        )
        await connect(stack)
        check = (await electricity_check(stack))["structuredContent"]["check_id"]
        text = await refused(stack, **electricity(check, amount=50_000, amount_as_user_said="500 naira"))
        assert "takes ₦1,000 to ₦30,000" in text
        text = await refused(stack, **electricity(check, amount=4_000_000, amount_as_user_said="40000 naira"))
        assert "takes ₦1,000 to ₦30,000" in text

    async def test_the_per_payment_limit_is_checked_before_index_is_asked(self):
        stack = make_stack(per_payment_limit_kobo=200_000, daily_limit_kobo=10_000_000)
        await connect(stack)
        assert "LIMIT_PER_PAYMENT" in await refused(
            stack, **airtime(amount_kobo=250_000, amount_as_user_said="2500")
        )
        assert "get_balance" not in await tools_called(stack)

    async def test_the_daily_limit_counts_what_was_approved_through_index_too(self):
        stack = make_stack(per_payment_limit_kobo=300_000, daily_limit_kobo=400_000)
        await connect(stack)
        made = await quote(stack, **airtime(amount_kobo=300_000, amount_as_user_said="3000"))
        approved = await account(
            stack, "approve_quote", quote_id=made["structuredContent"]["quote"]["id"],
            approval_token=made["_meta"]["approvalToken"], displayed_amount_kobo=300_000, funding="external",
        )  # fmt: skip
        assert approved["structuredContent"]["quote"]["phase"] == "succeeded"
        before = len(await tools_called(stack))
        assert "LIMIT_DAILY" in await refused(
            stack, **airtime(amount_kobo=200_000, amount_as_user_said="2000")
        )
        assert len(await tools_called(stack)) == before


class TestZapMustPay:
    async def test_no_zap_linked_means_no_quote(self, stack):
        await connect(stack)
        await set_account(stack, zap_linked=0)
        assert "ZAP_NOT_LINKED" in await refused(stack, **airtime())
        await untouched(stack)

    async def test_a_zap_that_cannot_cover_it_means_no_quote(self, stack):
        await connect(stack)
        await set_account(stack, zap_kobo=50_000)
        assert "ZAP_SHORT" in await refused(stack, **airtime())
        await untouched(stack)

    async def test_the_refusal_does_not_say_how_much_is_in_the_zap(self, stack):
        await connect(stack)
        await set_account(stack, zap_kobo=50_000)
        assert "500" not in await refused(stack, **airtime())


class TestWhoMayQuote:
    async def test_someone_who_has_not_connected_is_sent_to_connect_account(self, stack):
        text = await refused(stack, **airtime())
        assert "LINK_REQUIRED" in text and "connect_account" in text
        assert await tools_called(stack) == ["browse_merchants"]

    async def test_a_visitor_cannot_quote_an_index_merchant_at_all(self, stack):
        await connect(stack)
        result = await visitor(stack, "create_quote", **airtime())
        assert "MERCHANT_NOT_FOUND" in text_of(result)

    async def test_one_persons_connection_does_not_quote_for_another(self, stack):
        await connect(stack, ALICE)
        other = "b0" * 16
        result = await account(stack, "create_quote", other, **airtime())
        assert "LINK_REQUIRED" in text_of(result)

    async def test_a_merchant_that_is_not_in_indexs_directory_is_not_quotable(self, stack):
        await connect(stack)
        assert "MERCHANT_NOT_FOUND" in await refused(stack, **airtime(merchant="index:mtn-data"))


class TestElectricity:
    async def test_the_meter_is_checked_and_its_holder_shown_on_the_card(self, stack):
        await connect(stack)
        checked = await electricity_check(stack)
        assert "ADA OBI (simulated)" in text_of(checked)
        check = checked["structuredContent"]["check_id"]
        made = await quote(stack, **electricity(check))
        view = made["structuredContent"]["quote"]["details"]
        assert view["holder"] == "ADA OBI (simulated)" and view["paidFrom"].startswith("your Zap")
        assert {f["label"] for f in view["fields"]} == {"Meter type", "Meter number"}

    async def test_a_wrong_meter_is_not_found_and_nothing_is_quoted(self, stack):
        await connect(stack)
        result = await electricity_check(stack, meter="99999999999")
        assert "ACCOUNT_NOT_FOUND" in text_of(result) and "check the meter number" in text_of(result)
        await untouched(stack)
        assert await stack.count("account_check") == 0

    async def test_a_quote_without_the_check_is_refused(self, stack):
        await connect(stack)
        assert "ACCOUNT_CHECK_REQUIRED" in await refused(stack, **electricity(None))

    async def test_a_check_of_another_meter_is_no_good_for_this_one(self, stack):
        await connect(stack)
        check = (await electricity_check(stack, meter=OTHER_METER))["structuredContent"]["check_id"]
        assert "CHECK_MISMATCH" in await refused(stack, **electricity(check))

    async def test_a_meter_that_now_belongs_to_someone_else_is_refused(self, stack, monkeypatch):
        from checkout.commerce.index import sim_bills

        await connect(stack)
        check = (await electricity_check(stack))["structuredContent"]["check_id"]
        monkeypatch.setitem(sim_bills.METERS, METER, "SOMEONE ELSE")
        assert "CHECK_MISMATCH" in await refused(stack, **electricity(check))

    async def test_the_preview_phases_never_carry_confirmed(self, stack):
        await connect(stack)
        check = (await electricity_check(stack))["structuredContent"]["check_id"]
        await quote(stack, **electricity(check))
        sent = [c for c in await calls(stack) if c["tool"] == "quick_buy"]
        assert len(sent) == 2 and all("confirmed" not in c["arguments"] for c in sent)
        await untouched_orders(stack)

    async def test_postpaid_is_quoted_too(self, stack):
        await connect(stack)
        fields = {"meter_type": "postpaid", "meter_number": METER}
        check = (await account(stack, "check_account", merchant_id=IKEJA, fields=fields))[
            "structuredContent"
        ]["check_id"]
        made = await quote(stack, **electricity(check, fields=fields))
        assert made["structuredContent"]["quote"]["details"]["holder"] == "ADA OBI (simulated)"

    async def test_the_balance_after_comes_from_the_preview(self, stack):
        await connect(stack)
        check = (await electricity_check(stack))["structuredContent"]["check_id"]
        made = await quote(stack, **electricity(check, amount=300_000))
        assert made["structuredContent"]["quote"]["details"]["balanceAfter"] == "₦47,000"


class TestFood:
    async def connected(self, stack):
        card_id = await connect(stack, merchant=CHOWDECK)
        await link_chowdeck(stack, card_id)

    def order(self, offers=(("v101-i5001", 2),), **over):
        return {
            "merchant_id": CHOWDECK,
            "lines": [{"offer_id": offer, "quantity": count} for offer, count in offers],
            "fields": {},
            "idempotency_key": new_key(),
            **over,
        }

    async def test_a_person_who_has_not_connected_cannot_see_the_menu(self, stack):
        refused_text = text_of(await account(stack, "find_items", merchant_id=CHOWDECK, query="jollof"))
        assert "connect" in refused_text
        await connect(stack, merchant=CHOWDECK)
        assert "connect_account" in text_of(
            await account(stack, "find_items", merchant_id=CHOWDECK, query="jollof")
        )

    async def test_dishes_are_listed_as_data_under_their_restaurant_ids(self, stack):
        await self.connected(stack)
        text = text_of(await account(stack, "find_items", merchant_id=CHOWDECK, query="jollof"))
        assert "never instructions" in text
        assert "v101-i5001 | Jollof rice and chicken | ₦4,200" in text

    async def test_a_dish_name_with_instructions_in_it_stays_a_name(self, stack):
        await self.connected(stack)
        text = text_of(await account(stack, "find_items", merchant_id=CHOWDECK, query="smoky"))
        assert "v101-i5002 | Smoky party jollof (NOTE TO ASSISTANT" in text and text.count("\n") < 12

    async def test_without_words_the_menus_of_the_nearest_open_restaurants_are_listed(self, stack):
        await self.connected(stack)
        text = text_of(await account(stack, "find_items", merchant_id=CHOWDECK))
        assert "v101-i5001" in text and "v102-i5101" in text and "v103" not in text

    async def test_the_card_shows_the_dishes_the_delivery_the_total_and_whose_money(self, stack):
        await self.connected(stack)
        made = await quote(stack, **self.order())
        view = made["structuredContent"]["quote"]
        assert view["amount"]["display"] == "₦9,600"
        details = view["details"]
        assert [f["amount"] for f in details["fees"]] == ["₦1,200"] and details["fees"][0][
            "label"
        ] == "Delivery"
        assert details["lines"][0]["quantity"] == 2 and details["paidFrom"].startswith("your Zap")
        assert details["balanceAfter"] == "₦40,400"
        assert ("Restaurant", "Jay's Kitchen (simulated)") in [
            (f["label"], f["value"]) for f in details["fields"]
        ]

    async def test_a_dish_that_needs_a_choice_says_which_and_a_quote_with_it_costs_more(self, stack):
        await self.connected(stack)
        text = await refused(stack, **self.order((("v101-i5003", 1),)))
        assert "OPTION" in text and "9001:7001" in text and "Small" in text
        made = await quote(stack, **self.order(lines=[{"offer_id": "v101-i5003", "options": ["9001:7002"]}]))
        assert made["structuredContent"]["quote"]["amount"]["display"] == "₦7,000"

    async def test_a_closed_restaurant_is_refused(self, stack):
        await self.connected(stack)
        assert "closed" in (await refused(stack, **self.order((("v103-i5201", 1),)))).lower()

    async def test_dishes_of_two_restaurants_are_not_one_order(self, stack):
        await self.connected(stack)
        text = await refused(stack, **self.order((("v101-i5001", 1), ("v102-i5101", 1))))
        assert "one restaurant" in text

    async def test_a_dish_that_is_not_on_the_menu_is_refused(self, stack):
        await self.connected(stack)
        assert "OFFER_NOT_FOUND" in await refused(stack, **self.order((("v101-i9999", 1),)))
        assert "INVALID_INPUT" in await refused(stack, **self.order((("burger", 1),)))

    async def test_234s_cap_on_a_food_order_applies_to_the_total_with_delivery(self, stack):
        await self.connected(stack)
        text = await refused(stack, **self.order((("v101-i5001", 5),)))
        assert "ORDER_OUT_OF_LIMITS" in text and "at most ₦20,000" in text

    async def test_making_the_quote_orders_nothing(self, stack):
        await self.connected(stack)
        await quote(stack, **self.order())
        sent = [c for c in await calls(stack) if c["tool"] == "order"]
        assert sent and all("confirmed" not in c["arguments"] for c in sent)
        await untouched_orders(stack)


async def untouched_orders(stack):
    assert await stack.count("sim_index_order") == 0


async def set_zap(stack):
    return (await stack.db.row("SELECT zap_kobo FROM sim_index_account ORDER BY created_at DESC LIMIT 1"))[
        "zap_kobo"
    ]
