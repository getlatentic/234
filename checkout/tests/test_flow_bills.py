# SPDX-License-Identifier: AGPL-3.0-or-later
"""A television subscription or electricity bought through VTpass, end to end (docs/commerce.md and
docs/wallet.md, "Spending", "Reversals", "Refunds"): paid from the wallet or at the checkout, ordered with a
request id fixed by the quote, delivered, pending or failed with the money following each, a prepaid token on
the receipt, and an order VTpass takes back after delivering it."""

import json

import pytest

from checkout.commerce.model import Outcome
from checkout.commerce.vtpass_provider import VtpassProvider
from checkout.http import handle
from checkout.owner import acting_for
from checkout.receipts import TIMES
from checkout.vtpass.api import AccessCheck
from tests.bills_support import (
    FAILING,
    PENDING,
    PHONE,
    POSTPAID,
    PREPAID,
    RENEWAL_KOBO,
    SILENT,
    SMARTCARD,
    TIMEOUT,
    UNEXPECTED,
    check_id,
    electricity_quote,
    pay_at_checkout,
    pay_from_wallet,
    phase_of,
    renewal_quote,
    state_of,
    use_api,
)
from tests.commerce_support import approval, as_account, new_key, stored
from tests.connector_support import quote_of, text_of
from tests.support import ALICE
from tests.wallet_support import entries, journal_of

LAGOS_STAMP = r"^\d{12}qt[0-9a-f]{20}$"


async def vtpass_rows(stack):
    return await stack.rows("SELECT * FROM sim_vtpass ORDER BY created_at")


class TestADstvRenewalPaidFromTheWallet:
    async def test_is_delivered_at_once_for_the_total_and_orders_what_was_quoted(self, stack):
        made = await renewal_quote(stack)
        done = await pay_from_wallet(stack, made)
        assert done["phase"] == "succeeded" and done["amount"]["kobo"] == RENEWAL_KOBO
        assert await journal_of(stack).balance(ALICE) == 10_000_000 - RENEWAL_KOBO
        (order,) = await vtpass_rows(stack)
        assert (order["service_id"], order["billers_code"], order["subscription_type"]) == (
            "dstv",
            SMARTCARD,
            "renew",
        )
        assert (order["variation_code"], order["amount_naira"], order["phone"]) == (None, 10500.0, PHONE)

    async def test_the_request_id_is_the_lagos_minute_then_the_quote_and_is_kept(self, stack):
        import re

        made = await renewal_quote(stack)
        await pay_from_wallet(stack, made)
        request_id = (await stored(stack, quote_of(made)["id"]))["progress"]["fulfilment"]["requestId"]
        assert re.match(r"^\d{12}qt[0-9a-f]{20}$", request_id)
        assert [row["request_id"] for row in await vtpass_rows(stack)] == [request_id]

    async def test_the_receipt_names_the_bouquet_the_holder_the_validity_and_gives_no_token(self, stack):
        done = await pay_from_wallet(stack, await renewal_quote(stack))
        lines = {line["label"]: line["value"] for line in done["receipt"]["lines"]}
        assert done["receipt"]["title"] == "Subscription paid"
        assert lines[f"1 {TIMES} Renew DStv Confam"] == "₦10,500" and lines["Valid for"] == "1 month"
        assert lines["Account holder"] == "ADEOLA BALOGUN" and "Token" not in lines
        assert done["message"] is None

    async def test_a_bouquet_change_orders_the_bouquet(self, stack):
        ck = await check_id(stack, "dstv", SMARTCARD)
        fields = {"smartcard": SMARTCARD, "phone": PHONE}
        made = await as_account(
            stack, "create_quote", merchant_id="dstv", lines=[{"offer_id": "dstv-padi"}], fields=fields,
            check_id=ck, idempotency_key=new_key(),
        )  # fmt: skip
        done = await pay_from_wallet(stack, made)
        (order,) = await vtpass_rows(stack)
        assert (order["variation_code"], order["subscription_type"], order["amount_naira"]) == (
            "dstv-padi",
            "change",
            4400.0,
        )
        assert done["receipt"]["lines"][0]["label"] == f"1 {TIMES} Change to DStv Padi"

    async def test_the_card_and_the_reply_say_the_simulation_is_vtpasss(self, stack):
        done = await pay_from_wallet(stack, await renewal_quote(stack))
        assert done["mode"]["note"].startswith("Simulated VTpass") and "Mama" not in done["mode"]["label"]


class TestElectricityReceipts:
    async def test_a_prepaid_token_is_on_the_receipt_in_the_message_and_in_track_order(self, stack):
        done = await pay_from_wallet(stack, await electricity_quote(stack))
        lines = {line["label"]: line["value"] for line in done["receipt"]["lines"]}
        token = lines["Token"]
        assert len(token.replace(" ", "")) == 20 and lines["Units"] == "71.4 kWh" and "Tariff" in lines
        assert done["receipt"]["title"] == "Electricity paid"
        assert done["message"].startswith("Delivered. Token: " + token)
        told = text_of(await as_account(stack, "track_order", quote_id=done["id"]))
        assert token in told and "71.4 kWh" in told

    async def test_the_token_is_not_in_the_audit_log(self, stack):
        done = await pay_from_wallet(stack, await electricity_quote(stack))
        token = {line["label"]: line["value"] for line in done["receipt"]["lines"]}["Token"]
        assert token.replace(" ", "") not in "\n".join(stack.audit_lines).replace(" ", "")

    async def test_a_postpaid_payment_settles_with_no_token(self, stack):
        done = await pay_from_wallet(stack, await electricity_quote(stack, POSTPAID, "postpaid"))
        labels = [line["label"] for line in done["receipt"]["lines"]]
        assert done["phase"] == "succeeded" and "Token" not in labels and "Units" not in labels
        assert done["message"] is None and "Address" in labels
        (order,) = await vtpass_rows(stack)
        assert (order["variation_code"], order["amount_naira"]) == ("postpaid", 5000.0)

    async def test_a_prepaid_order_is_sent_as_prepaid_with_the_amount_in_naira(self, stack):
        await pay_from_wallet(stack, await electricity_quote(stack))
        (order,) = await vtpass_rows(stack)
        assert (order["service_id"], order["variation_code"], order["billers_code"]) == (
            "ikeja-electric",
            "prepaid",
            PREPAID,
        )

    async def test_the_same_receipt_is_read_again_by_verify(self, stack):
        done = await pay_from_wallet(stack, await electricity_quote(stack))
        again = quote_of(await as_account(stack, "verify_quote", quote_id=done["id"]))
        assert again["receipt"] == done["receipt"]


class TestPaidAtTheCheckout:
    async def test_a_renewal_is_ordered_only_after_the_payment_and_delivered(self, stack):
        made = await renewal_quote(stack)
        approved = quote_of(await as_account(stack, "approve_quote", **approval(made)))
        assert approved["phase"] == "awaiting_checkout" and await vtpass_rows(stack) == []
        done = await pay_at_checkout(stack, made)
        assert done["phase"] == "succeeded" and len(await vtpass_rows(stack)) == 1

    async def test_a_declined_checkout_orders_nothing(self, stack):
        made = await renewal_quote(stack)
        approved = quote_of(await as_account(stack, "approve_quote", **approval(made)))
        await stack.complete_checkout(approved["checkoutUrl"], "failed")
        await as_account(stack, "verify_quote", quote_id=approved["id"])
        assert await vtpass_rows(stack) == []

    async def test_a_prepaid_token_comes_with_a_checkout_payment_too(self, stack):
        done = await pay_at_checkout(stack, await electricity_quote(stack))
        assert "Token" in {line["label"]: line["value"] for line in done["receipt"]["lines"]}


class TestTheThreeOutcomes:
    @pytest.mark.parametrize("kind", ["tv", "electricity"])
    async def test_delivered_settles_once(self, stack, kind):
        made = await (renewal_quote(stack) if kind == "tv" else electricity_quote(stack))
        done = await pay_from_wallet(stack, made)
        for _ in range(3):
            assert await phase_of(stack, done["id"]) == "succeeded"
        assert len(await vtpass_rows(stack)) == 1
        assert len([line for line in stack.audit_lines if '"fulfilment.delivered"' in line]) == 1

    @pytest.mark.parametrize("code", [PENDING, UNEXPECTED, SILENT, TIMEOUT])
    @pytest.mark.parametrize("kind", ["tv", "electricity"])
    async def test_not_clearly_delivered_is_pending_never_failed_and_the_money_stays_held(
        self, stack, kind, code
    ):
        made = await (renewal_quote(stack, code) if kind == "tv" else electricity_quote(stack, code))
        done = await pay_from_wallet(stack, made)
        assert (done["phase"], done["poll"]) == ("processing", True)
        assert await phase_of(stack, done["id"]) == "processing"
        assert await entries(stack, "refund") == [] and len(await vtpass_rows(stack)) == 1

    @pytest.mark.parametrize("kind", ["tv", "electricity"])
    async def test_pending_is_requeried_not_ordered_again_and_then_delivers(self, stack, kind):
        made = await (renewal_quote(stack, PENDING) if kind == "tv" else electricity_quote(stack, PENDING))
        done = await pay_from_wallet(stack, made)
        for _ in range(3):
            await as_account(stack, "verify_quote", quote_id=done["id"])
        assert len(await vtpass_rows(stack)) == 1
        stack.clock.advance(21)
        assert await phase_of(stack, done["id"]) == "succeeded"
        assert await state_of(stack, done["id"]) == "settled"

    @pytest.mark.parametrize("kind", ["tv", "electricity"])
    async def test_failed_gives_the_wallet_its_money_back_once(self, stack, kind):
        made = await (renewal_quote(stack, FAILING) if kind == "tv" else electricity_quote(stack, FAILING))
        done = await pay_from_wallet(stack, made)
        assert done["phase"] == "failed" and "back in the wallet" in done["message"]
        assert "did not deliver" in done["message"]
        for _ in range(3):
            await as_account(stack, "verify_quote", quote_id=done["id"])
        (refund,) = await entries(stack, "refund")
        assert refund["ref"] == done["id"] and await journal_of(stack).balance(ALICE) == 10_000_000
        assert done["receipt"] is None

    @pytest.mark.parametrize("kind", ["tv", "electricity"])
    async def test_failed_after_a_checkout_payment_owes_the_payer_a_paystack_refund(self, stack, kind):
        made = await (renewal_quote(stack, FAILING) if kind == "tv" else electricity_quote(stack, FAILING))
        done = await pay_at_checkout(stack, made)
        assert done["phase"] == "attention" and done["refund"]["title"].startswith("Refunding")
        await stack.run_jobs()
        (refund,) = await stack.rows("SELECT state, amount_kobo FROM quote_refund")
        assert (refund["state"], refund["amount_kobo"]) == ("sent", quote_of(made)["amount"]["kobo"])

    async def test_a_request_vtpass_never_saw_is_ordered_again_with_the_same_id(self, stack, monkeypatch):
        placed = []
        real = VtpassProvider.fulfil

        async def counting(self, quote):
            placed.append(quote.progress["fulfilment"]["requestId"])
            return await real(self, quote)

        async def unseen(self, quote):
            return Outcome("pending", "INVALID REQUEST ID", unknown_request=True)

        monkeypatch.setattr(VtpassProvider, "fulfil", counting)
        made = await renewal_quote(stack, PENDING)
        done = await pay_from_wallet(stack, made)
        monkeypatch.setattr(VtpassProvider, "status", unseen)
        await as_account(stack, "verify_quote", quote_id=done["id"])
        assert len(placed) == 2 and placed[0] == placed[1]
        assert len(await vtpass_rows(stack)) == 1


class TestNothingIsQuotedForAVtpassThatCannotDeliver:
    async def test_an_account_vtpass_refuses_quotes_nothing(self, stack):
        async def refused():
            return AccessCheck(False, reason="VTpass refused this account's credentials (HTTP 401).")

        ck = await check_id(stack, "dstv", SMARTCARD)
        use_api(stack, check_access=refused)
        from tests.bills_support import renewal

        made = await as_account(stack, "create_quote", **renewal(ck))
        assert text_of(made).startswith("PROVIDER_ERROR") and await stack.count("quotes") == 0

    async def test_a_vtpass_wallet_that_cannot_cover_the_order_quotes_nothing(self, stack):
        async def poor():
            return AccessCheck(True, balance_kobo=100_000)

        ck = await check_id(stack, "dstv", SMARTCARD)
        use_api(stack, check_access=poor)
        from tests.bills_support import renewal

        made = await as_account(stack, "create_quote", **renewal(ck))
        assert "VTpass wallet holds less than ₦10,500" in text_of(made)


class TestWithAServiceFee:
    async def test_the_wallet_pays_the_total_and_vtpass_is_ordered_the_bill_alone(self):
        from tests.support import make_stack

        stack = make_stack(bills_service_fee_kobo=25_000)
        done = await pay_from_wallet(stack, await renewal_quote(stack))
        assert done["amount"]["kobo"] == RENEWAL_KOBO + 25_000
        assert await journal_of(stack).balance(ALICE) == 10_000_000 - RENEWAL_KOBO - 25_000
        (order,) = await vtpass_rows(stack)
        assert order["amount_naira"] == 10500.0
        assert ("Service fee", "₦250") in [(x["label"], x["value"]) for x in done["receipt"]["lines"]]

    async def test_a_failed_order_gives_back_the_fee_with_the_bill(self):
        from tests.support import make_stack

        stack = make_stack(bills_service_fee_kobo=25_000)
        done = await pay_from_wallet(stack, await renewal_quote(stack, FAILING))
        assert done["phase"] == "failed" and await journal_of(stack).balance(ALICE) == 10_000_000


async def reverse_at_vtpass(stack, quote_id):
    """VTpass takes the order back and sends its callback; then the queued work runs."""
    request_id = (await stored(stack, quote_id))["progress"]["fulfilment"]["requestId"]
    answer = await handle(stack.app, "POST", f"/test/vtpass-reverse/{request_id}", {}, b"")
    await stack.run_jobs()
    return answer


class TestAnOrderVtpassTakesBackAfterDelivering:
    @pytest.mark.parametrize("kind", ["tv", "electricity"])
    async def test_a_wallet_payment_comes_back_once_and_the_quote_ends_reversed(self, stack, kind):
        made = await (renewal_quote(stack) if kind == "tv" else electricity_quote(stack))
        done = await pay_from_wallet(stack, made)
        answer = await reverse_at_vtpass(stack, done["id"])
        assert json.loads(answer.body) == {"response": "success"}
        assert await state_of(stack, done["id"]) == "reversed"
        (refund,) = await entries(stack, "refund")
        assert refund["amount_kobo"] == done["amount"]["kobo"]
        assert await journal_of(stack).balance(ALICE) == 10_000_000
        view = quote_of(await as_account(stack, "track_order", quote_id=done["id"]))
        assert view["phase"] == "failed" and "reversed this order after delivering it" in view["message"]

    async def test_the_same_callback_twice_reverses_and_refunds_once(self, stack):
        done = await pay_from_wallet(stack, await electricity_quote(stack))
        await reverse_at_vtpass(stack, done["id"])
        await reverse_at_vtpass(stack, done["id"])
        assert len(await entries(stack, "refund")) == 1

    async def test_a_checkout_payment_reversed_owes_a_paystack_refund(self, stack):
        made = await renewal_quote(stack)
        done = await pay_at_checkout(stack, made)
        await reverse_at_vtpass(stack, done["id"])
        assert await state_of(stack, done["id"]) == "reversed"
        assert "refund.due" in "\n".join(stack.audit_lines)
        (refund,) = await stack.rows("SELECT state, amount_kobo FROM quote_refund")
        assert refund["amount_kobo"] == RENEWAL_KOBO

    async def test_a_callback_vtpass_does_not_confirm_changes_nothing(self, stack):
        done = await pay_from_wallet(stack, await renewal_quote(stack))
        request_id = (await stored(stack, done["id"]))["progress"]["fulfilment"]["requestId"]
        from checkout.vtpass.sim import reversal_update
        from checkout.vtpass.sim_store import SimOrder

        body = reversal_update(SimOrder(request_id, "dstv", PHONE, 10500, None, "success", 0), 0)
        await handle(stack.app, "POST", "/hooks/vtpass", {}, body)
        await stack.run_jobs()
        assert await state_of(stack, done["id"]) == "settled" and await entries(stack, "refund") == []

    async def test_a_reversal_takes_the_bill_off_the_days_limit(self, stack):
        done = await pay_from_wallet(stack, await renewal_quote(stack))
        with acting_for(ALICE):
            assert (await stack.ledger.budget()).spent_today_kobo == RENEWAL_KOBO
        await reverse_at_vtpass(stack, done["id"])
        with acting_for(ALICE):
            assert (await stack.ledger.budget()).spent_today_kobo == 0

    async def test_a_shop_order_is_never_reversed_by_a_callback(self, stack):
        from tests.commerce_support import fund, meal

        await fund(stack, 5_000_000, ALICE)
        made = await as_account(stack, "create_quote", **meal())
        done = quote_of(await as_account(stack, "approve_quote", **approval(made, funding="wallet")))
        body = json.dumps(
            {
                "type": "transaction-update",
                "data": {"code": "040", "requestId": "x" + done["id"].replace("-", "")},
            }
        ).encode()
        await handle(stack.app, "POST", "/hooks/vtpass", {}, body)
        await stack.run_jobs()
        assert await state_of(stack, done["id"]) == "settled" and await entries(stack, "refund") == []
