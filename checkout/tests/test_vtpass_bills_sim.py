# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated VTpass's television and electricity through the real client (vtpass/sim_bills.py): the
scenarios VTpass's documentation lists for a smartcard and a meter, an account check that refuses a number it
does not know, a prepaid token, and a reversal after delivery."""

import pytest

from checkout.config import SimulatorSettings
from checkout.vtpass.api import VtpassError
from checkout.vtpass.bills import BillCheck, BillOrder, BillRefused
from checkout.vtpass.sim_store import VtpassSimStore
from tests.bills_support import (
    FAILING,
    PENDING,
    POSTPAID,
    PREPAID,
    SILENT,
    SMARTCARD,
    TIMEOUT,
    UNEXPECTED,
    WRONG,
)
from tests.support import make_stack


def vtpass_of(**simulator):
    stack = make_stack(simulator=SimulatorSettings(**simulator))
    return stack, stack.app.contexts["airtime"].vtpass


def meter(code: str, request_id: str, kind: str = "prepaid", **over) -> BillOrder:
    return BillOrder(
        **{
            "request_id": request_id,
            "service_id": "ikeja-electric",
            "billers_code": code,
            "phone": "08031234567",
            "amount_kobo": 500_000,
            "meter_type": kind,
        }
        | over
    )


def card(code: str, request_id: str, **over) -> BillOrder:
    return BillOrder(
        **{
            "request_id": request_id,
            "service_id": "dstv",
            "billers_code": code,
            "phone": "08031234567",
            "amount_kobo": 1_050_000,
            "subscription_type": "renew",
        }
        | over
    )


class TestAnAccountCheck:
    async def test_knows_the_documented_smartcard_and_returns_the_holder_the_bouquet_and_the_renewal(self):
        _, api = vtpass_of()
        found = await api.verify_bill(BillCheck("dstv", SMARTCARD))
        assert (found.holder, found.bouquet, found.renewal_kobo) == (
            "ADEOLA BALOGUN",
            "DStv Confam",
            1_050_000,
        )
        assert found.due_date == "2026-11-02T00:00:00"

    async def test_knows_the_documented_prepaid_and_postpaid_meters_and_their_least(self):
        _, api = vtpass_of()
        prepaid = await api.verify_bill(BillCheck("ikeja-electric", PREPAID, "prepaid"))
        postpaid = await api.verify_bill(BillCheck("ikeja-electric", POSTPAID, "postpaid"))
        assert (prepaid.holder, prepaid.min_kobo, prepaid.arrears_kobo) == ("FUNMI AKINTOLA", 100_000, None)
        assert (postpaid.holder, postpaid.arrears_kobo) == ("KELECHI NWOSU", 835_050)
        assert prepaid.max_kobo is None

    async def test_states_a_distribution_companys_own_least(self):
        _, api = vtpass_of()
        found = await api.verify_bill(BillCheck("ibadan-electric", PREPAID, "prepaid"))
        assert found.min_kobo == 200_000

    @pytest.mark.parametrize(
        ("service", "code", "kind"),
        [
            ("dstv", WRONG, None),
            ("gotv", "1234567890", None),
            ("startimes", "1234567890", None),
            ("ikeja-electric", WRONG, "prepaid"),
            ("ikeja-electric", PREPAID, "postpaid"),
            ("eko-electric", POSTPAID, "prepaid"),
        ],
    )
    async def test_refuses_a_number_it_does_not_know_and_a_meter_of_the_wrong_type(self, service, code, kind):
        _, api = vtpass_of()
        with pytest.raises(BillRefused):
            await api.verify_bill(BillCheck(service, code, kind))

    async def test_verifies_the_trigger_numbers_so_the_other_outcomes_can_be_shown(self):
        _, api = vtpass_of()
        for code in (PENDING, UNEXPECTED, SILENT, TIMEOUT, FAILING):
            assert (await api.verify_bill(BillCheck("ikeja-electric", code, "prepaid"))).holder
            assert (await api.verify_bill(BillCheck("dstv", code))).holder

    async def test_every_one_of_the_twelve_companies_verifies_the_documented_meter(self):
        _, api = vtpass_of()
        from checkout.vtpass.bills import SERVICES

        for service, (kind, _) in SERVICES.items():
            if kind == "electricity":
                assert (await api.verify_bill(BillCheck(service, PREPAID, "prepaid"))).holder, service

    async def test_a_service_it_does_not_sell_is_refused(self):
        _, api = vtpass_of()
        with pytest.raises(BillRefused):
            await api.verify_bill(BillCheck("showmax", "08011111111"))


class TestTheSandboxScenarios:
    @pytest.mark.parametrize(
        ("code", "status"),
        [
            (SMARTCARD, "delivered"),
            (PENDING, "pending"),
            (UNEXPECTED, "pending"),
            (SILENT, "pending"),
            (TIMEOUT, "pending"),
            (FAILING, "failed"),
            (WRONG, "failed"),
        ],
    )
    async def test_a_television_order_for_a_smartcard(self, code, status):
        _, api = vtpass_of()
        assert (await api.buy_bill(card(code, f"202610141200card-{code}"))).status == status

    @pytest.mark.parametrize(
        ("code", "kind", "status"),
        [
            (PREPAID, "prepaid", "delivered"),
            (POSTPAID, "postpaid", "delivered"),
            (PENDING, "prepaid", "pending"),
            (UNEXPECTED, "prepaid", "pending"),
            (SILENT, "prepaid", "pending"),
            (TIMEOUT, "prepaid", "pending"),
            (FAILING, "prepaid", "failed"),
            (WRONG, "prepaid", "failed"),
            (POSTPAID, "prepaid", "failed"),
        ],
    )
    async def test_an_electricity_order_for_a_meter(self, code, kind, status):
        _, api = vtpass_of()
        assert (await api.buy_bill(meter(code, f"202610141200meter-{code}-{kind}", kind))).status == status

    async def test_a_pending_order_is_delivered_after_the_wait_and_a_repeated_id_is_not_placed_twice(self):
        stack, api = vtpass_of(pending_seconds=20)
        assert (await api.buy_bill(meter(PENDING, "202610141200pend1"))).status == "pending"
        stack.clock.advance(10)
        assert (await api.requery("202610141200pend1")).status == "pending"
        stack.clock.advance(10)
        assert (await api.requery("202610141200pend1")).status == "delivered"
        again = await api.buy_bill(meter(PENDING, "202610141200pend1"))
        assert again.code == "014" and again.status == "pending"

    async def test_a_request_it_never_saw_is_the_unknown_request(self):
        _, api = vtpass_of()
        assert (await api.requery("202610141200nothing")).unknown_request is True

    async def test_a_renewal_at_another_amount_than_the_cards_fails(self):
        _, api = vtpass_of()
        assert (
            await api.buy_bill(card(SMARTCARD, "202610141200ren1", amount_kobo=999_900))
        ).status == "failed"

    @pytest.mark.parametrize(
        "over",
        [
            {"subscription_type": None},
            {"subscription_type": "change"},
            {"subscription_type": "renew", "variation_code": "dstv-padi"},
        ],
    )
    async def test_a_dstv_order_that_does_not_say_clearly_what_it_is_is_invalid(self, over):
        _, api = vtpass_of()
        outcome = await api.buy_bill(card(SMARTCARD, "202610141200bad1", **over))
        assert (outcome.status, outcome.code) == ("failed", "011")

    async def test_a_bouquet_change_names_the_bouquet_and_pays_its_price(self):
        _, api = vtpass_of()
        order = card(SMARTCARD, "202610141200chg1", variation_code="dstv-padi", subscription_type="change")
        assert (await api.buy_bill(order)).status == "delivered"

    async def test_a_meter_order_needs_a_type(self):
        _, api = vtpass_of()
        assert (await api.buy_bill(meter(PREPAID, "202610141200nt1", None))).code == "011"

    async def test_showmax_delivers_to_a_valid_phone_with_a_voucher_and_fails_a_bad_one(self):
        _, api = vtpass_of()
        order = BillOrder(
            "202610141200smx1", "showmax", "08031234567", "08031234567", 320_000, "showmax-standard"
        )
        outcome = await api.buy_bill(order)
        assert outcome.status == "delivered" and dict(outcome.receipt)["Voucher"].startswith("SMX-")
        bad = BillOrder("202610141200smx2", "showmax", "12345", "08031234567", 320_000, "showmax-standard")
        assert (await api.buy_bill(bad)).status == "failed"

    async def test_startimes_takes_a_bouquet_without_a_subscription_type(self):
        _, api = vtpass_of()
        order = BillOrder("202610141200st1", "startimes", SMARTCARD, "08031234567", 370_000, "basic")
        assert (await api.buy_bill(order)).status == "delivered"


class TestWhatADeliveredOrderGives:
    async def test_a_prepaid_meter_gets_a_token_units_and_a_tariff_the_same_on_a_requery(self):
        _, api = vtpass_of()
        first = await api.buy_bill(meter(PREPAID, "202610141200tok1"))
        again = await api.requery("202610141200tok1")
        assert [label for label, _ in first.receipt] == ["Token", "Units", "Tariff"]
        assert dict(first.receipt)["Units"] == "71.4 kWh"
        assert again.receipt == first.receipt

    async def test_two_orders_get_two_tokens(self):
        _, api = vtpass_of()
        one = await api.buy_bill(meter(PREPAID, "202610141200tok2"))
        two = await api.buy_bill(meter(PREPAID, "202610141200tok3"))
        assert dict(one.receipt)["Token"] != dict(two.receipt)["Token"]

    async def test_a_postpaid_meter_gets_no_token(self):
        _, api = vtpass_of()
        assert (await api.buy_bill(meter(POSTPAID, "202610141200post1", "postpaid"))).receipt == ()

    async def test_a_television_subscription_gets_no_token(self):
        _, api = vtpass_of()
        assert (await api.buy_bill(card(SMARTCARD, "202610141200tv01"))).receipt == ()

    async def test_a_pending_or_failed_order_gives_nothing(self):
        _, api = vtpass_of()
        assert (await api.buy_bill(meter(PENDING, "202610141200nil1"))).receipt == ()
        assert (await api.buy_bill(meter(FAILING, "202610141200nil2"))).receipt == ()


class TestAReversalAfterDelivery:
    async def test_is_taken_back_once_and_a_requery_then_says_reversed(self):
        stack, api = vtpass_of()
        await api.buy_bill(meter(PREPAID, "202610141200rev1"))
        store = VtpassSimStore(stack.db)
        assert await store.reverse("202610141200rev1", 1) is not None
        assert await store.reverse("202610141200rev1", 2) is None
        outcome = await api.requery("202610141200rev1")
        assert (outcome.status, outcome.reversed, outcome.code) == ("failed", True, "040")

    async def test_a_failed_order_cannot_be_reversed(self):
        stack, api = vtpass_of()
        await api.buy_bill(meter(FAILING, "202610141200rev2"))
        assert await VtpassSimStore(stack.db).reverse("202610141200rev2", 1) is None


class TestBouquets:
    @pytest.mark.parametrize("service", ["dstv", "gotv", "startimes", "showmax"])
    async def test_each_television_service_lists_fixed_price_bouquets(self, service):
        _, api = vtpass_of()
        found = await api.bouquets(service)
        assert len(found) >= 3 and all(b.amount_kobo > 0 for b in found)

    async def test_dstv_lists_the_confam_bouquet_at_the_renewal_amount_of_the_documented_card(self):
        _, api = vtpass_of()
        confam = next(b for b in await api.bouquets("dstv") if b.code == "dstv-confam")
        assert confam.amount_kobo == 1_050_000

    async def test_a_service_it_does_not_sell_has_no_list(self):
        _, api = vtpass_of()
        with pytest.raises(VtpassError):
            await api.bouquets("water")
