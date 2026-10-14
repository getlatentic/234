# SPDX-License-Identifier: AGPL-3.0-or-later
"""What happens after the person approves an Index quote: Index is asked to place the order once, from the
person's own Zap, with nothing from 234's wallet; a repeated or racing approval places it once; and what Index
or the network does with the order ends in one of the three outcomes without a second send."""

import asyncio

import pytest

from checkout.commerce.index.following import WINDOW_MS
from checkout.http import handle
from checkout.owner import acting_for, remembering_for
from tests.commerce_support import approval, fund, stored
from tests.index_support import (
    CHOWDECK,
    METER,
    account,
    airtime,
    calls,
    connect,
    electricity,
    electricity_check,
    link_chowdeck,
    new_key,
    ok,
    press_approve,
    quote,
    set_setting,
    text_of,
    tools_called,
)
from tests.support import ALICE, BOB

OUTCOME = "confirm_outcome"


def view_of(result):
    return result["structuredContent"]["quote"]


async def sim_orders(stack):
    return await stack.rows("SELECT * FROM sim_index_order")


async def zap(stack):
    return (await stack.db.row("SELECT zap_kobo FROM sim_index_account ORDER BY created_at DESC LIMIT 1"))[
        "zap_kobo"
    ]


async def charges(stack):
    return [c for c in await calls(stack) if c["tool"] in ("quick_buy", "order") and _charges(c)]


def _charges(call):
    arguments = call["arguments"]
    return arguments.get("confirmed") is True or (
        call["tool"] == "quick_buy" and arguments["category"] == "airtime"
    )


async def made(stack, **request):
    await connect(stack)
    return await quote(stack, **(request or airtime()))


async def verify(stack, made_quote, owner=ALICE):
    return await account(stack, "verify_quote", owner, quote_id=view_of(made_quote)["id"])


class TestAirtime:
    async def test_approving_places_the_order_and_ends_delivered_with_a_receipt(self, stack):
        pending = await made(stack)
        done = ok(await press_approve(stack, pending))
        view = view_of(done)
        assert view["phase"] == "succeeded" and view["receipt"]["title"] == "Order delivered"
        labels = {line["label"]: line["value"] for line in view["receipt"]["lines"]}
        assert labels["Paid from"] == "your Zap balance at Paystack Index" and labels["Order"].startswith(
            "ord-"
        )
        assert await zap(stack) == 5_000_000 - 100_000 and len(await sim_orders(stack)) == 1

    async def test_nothing_is_charged_until_the_person_approves(self, stack):
        await made(stack)
        assert await charges(stack) == [] and await sim_orders(stack) == []
        assert not [c for c in await calls(stack) if c["confirmed"]]

    async def test_234s_wallet_is_not_touched(self, stack):
        await fund(stack, 5_000_000, ALICE)
        pending = await made(stack)
        ok(await press_approve(stack, pending))
        assert await stack.count("wallet_entry") == 1
        entries = await stack.rows("SELECT kind FROM wallet_entry")
        assert [e["kind"] for e in entries] == ["fund"]

    async def test_the_quote_is_marked_as_paid_by_someone_else(self, stack):
        pending = await made(stack)
        ok(await press_approve(stack, pending))
        held = await stored(stack, view_of(pending)["id"])
        assert held["state"] == "settled" and held["progress"]["funding"] == "external"
        assert "paystackReference" not in held["progress"] and "indexSend" in held["progress"]

    async def test_a_wrong_token_or_amount_places_nothing(self, stack):
        pending = await made(stack)
        bad = await press_approve(stack, pending, approval_token="0" * 64)
        assert "APPROVAL_DENIED" in text_of(bad)
        wrong = await press_approve(stack, pending, displayed_amount_kobo=1)
        assert "AMOUNT_MISMATCH" in text_of(wrong)
        assert await charges(stack) == []

    async def test_another_person_cannot_approve_it(self, stack):
        pending = await made(stack)
        await connect(stack, BOB)
        result = await press_approve(stack, pending, BOB)
        assert result.get("isError") and await charges(stack) == []

    async def test_a_declined_quote_places_nothing(self, stack):
        pending = await made(stack)
        done = ok(
            await account(
                stack,
                "decline_quote",
                quote_id=view_of(pending)["id"],
                approval_token=pending["_meta"]["approvalToken"],
            )
        )
        assert view_of(done)["phase"] == "declined" and await charges(stack) == []

    async def test_an_expired_quote_places_nothing(self, stack):
        pending = await made(stack)
        stack.clock.advance(11 * 60)
        assert "QUOTE_EXPIRED" in text_of(await press_approve(stack, pending))
        assert await charges(stack) == []

    async def test_a_token_that_has_expired_is_renewed_and_the_order_still_goes(self, stack):
        pending = await made(stack)
        await handle(stack.app, "POST", "/test/index/expire", {}, b"")
        assert view_of(ok(await press_approve(stack, pending)))["phase"] == "succeeded"


class TestElectricityAndFood:
    async def test_a_prepaid_token_is_on_the_receipt(self, stack):
        await connect(stack)
        check = (await electricity_check(stack))["structuredContent"]["check_id"]
        pending = await quote(stack, **electricity(check))
        done = ok(await press_approve(stack, pending))
        labels = {line["label"]: line["value"] for line in view_of(done)["receipt"]["lines"]}
        assert labels["Prepaid token"] == "1234-5678-9012-3456-7890"
        assert labels["Meter number"] == METER and labels["Meter type"] == "prepaid"

    async def test_only_the_last_electricity_call_carries_confirmed_and_it_comes_after_the_approval(
        self, stack
    ):
        await connect(stack)
        check = (await electricity_check(stack))["structuredContent"]["check_id"]
        pending = await quote(stack, **electricity(check))
        before = [c["confirmed"] for c in await calls(stack) if c["tool"] == "quick_buy"]
        assert before == [False, False]
        ok(await press_approve(stack, pending))
        after = [c["confirmed"] for c in await calls(stack) if c["tool"] == "quick_buy"]
        assert after == [False, False, True]

    async def test_a_food_order_ends_with_its_pin_and_the_total_it_was_quoted(self, stack):
        card_id = await connect(stack, merchant=CHOWDECK)
        await link_chowdeck(stack, card_id)
        request = {
            "merchant_id": CHOWDECK, "lines": [{"offer_id": "v101-i5001", "quantity": 2}], "fields": {},
            "idempotency_key": new_key(),
        }  # fmt: skip
        pending = await quote(stack, **request)
        done = ok(await press_approve(stack, pending))
        labels = {line["label"]: line["value"] for line in view_of(done)["receipt"]["lines"]}
        assert labels["Delivery PIN"] == "4821" and labels["Restaurant"] == "Jay's Kitchen (simulated)"
        assert (await sim_orders(stack))[0]["total_kobo"] == 960_000
        assert [c["tool"] for c in await calls(stack) if c["confirmed"]] == ["order"]

    async def test_a_food_price_that_moved_since_the_quote_is_not_charged(self, stack, monkeypatch):
        from checkout.commerce.index import sim_chowdeck

        card_id = await connect(stack, merchant=CHOWDECK)
        await link_chowdeck(stack, card_id)
        request = {
            "merchant_id": CHOWDECK,
            "lines": [{"offer_id": "v101-i5001"}],
            "fields": {},
            "idempotency_key": new_key(),
        }
        pending = await quote(stack, **request)
        monkeypatch.setattr(sim_chowdeck, "DELIVERY_KOBO", 500_000)
        done = ok(await press_approve(stack, pending))
        assert view_of(done)["phase"] == "failed" and "price" in view_of(done)["message"]
        assert await charges(stack) == [] and await sim_orders(stack) == []


class TestOnlyOneSend:
    async def test_pressing_approve_twice_places_one_order(self, stack):
        pending = await made(stack)
        ok(await press_approve(stack, pending))
        again = await press_approve(stack, pending)
        assert view_of(ok(again))["phase"] == "succeeded"
        assert len(await charges(stack)) == 1 and await zap(stack) == 5_000_000 - 100_000

    async def test_two_approvals_together_place_one_order(self, stack):
        pending = await made(stack)
        both = await asyncio.gather(press_approve(stack, pending), press_approve(stack, pending))
        assert all("isError" not in r for r in both)
        assert len(await charges(stack)) == 1 and len(await sim_orders(stack)) == 1

    async def test_asking_again_and_the_minutes_sweep_place_nothing_more(self, stack):
        pending = await made(stack)
        ok(await press_approve(stack, pending))
        for _ in range(3):
            ok(await verify(stack, pending))
        await stack.app.background.rechecks.sweep()
        await stack.run_jobs()
        assert len(await charges(stack)) == 1

    async def test_the_send_is_marked_before_it_is_made(self, stack):
        pending = await made(stack)
        quote_id = view_of(pending)["id"]
        ok(await press_approve(stack, pending))
        assert (await stored(stack, quote_id))["progress"]["indexSend"]["at"] > 0

    async def test_a_marker_without_an_answer_means_the_order_is_asked_about_never_sent_again(self, stack):
        pending = await made(stack)
        quote_id = view_of(pending)["id"]
        await stack.db.execute(
            "UPDATE quotes SET progress = json_patch(progress, ?) WHERE id = ?",
            '{"indexSend": {"at": %d}}' % stack.clock.now(), quote_id,
        )  # fmt: skip
        ok(await press_approve(stack, pending))
        assert await charges(stack) == []
        assert "get_recent_activity" in await tools_called(stack)
        assert (await stored(stack, quote_id))["state"] == "approved"


class TestThreeOutcomes:
    async def test_index_refusing_is_a_failure_with_nothing_charged_and_no_refund_owed(self, stack):
        pending = await made(stack)
        await set_setting(stack, OUTCOME, "failed")
        done = ok(await press_approve(stack, pending))
        assert view_of(done)["phase"] == "failed" and "Nothing was charged" in view_of(done)["message"]
        held = await stored(stack, view_of(pending)["id"])
        assert held["state"] == "failed" and await stack.count("quote_refund") == 0
        assert await zap(stack) == 5_000_000 and len(await charges(stack)) == 1

    async def test_a_failed_order_is_never_sent_again(self, stack):
        pending = await made(stack)
        await set_setting(stack, OUTCOME, "failed")
        ok(await press_approve(stack, pending))
        await set_setting(stack, OUTCOME, "delivered")
        ok(await verify(stack, pending))
        assert len(await charges(stack)) == 1 and await sim_orders(stack) == []

    async def test_an_order_whose_answer_was_lost_after_the_charge_is_found_by_the_zap_history(self, stack):
        pending = await made(stack)
        await set_setting(stack, OUTCOME, "dropped")
        first = ok(await press_approve(stack, pending))
        assert view_of(first)["phase"] == "processing" and "may have gone through" in str(first)
        done = ok(await verify(stack, pending))
        assert view_of(done)["phase"] == "succeeded"
        assert len(await charges(stack)) == 1 and await zap(stack) == 5_000_000 - 100_000

    async def test_an_order_that_never_reached_index_stays_pending_then_fails_and_is_never_resent(
        self, stack
    ):
        pending = await made(stack)
        await set_setting(stack, OUTCOME, "lost")
        first = ok(await press_approve(stack, pending))
        assert view_of(first)["phase"] == "processing"
        await set_setting(stack, OUTCOME, "delivered")
        assert view_of(ok(await verify(stack, pending)))["phase"] == "processing"
        stack.clock.advance(WINDOW_MS // 1000 + 61)
        done = ok(await verify(stack, pending))
        assert view_of(done)["phase"] == "failed" and "no matching debit" in view_of(done)["message"]
        assert (
            len(await charges(stack)) == 1 and await sim_orders(stack) == [] and await zap(stack) == 5_000_000
        )

    async def test_an_order_index_has_not_finished_is_asked_about_until_it_has(self, stack):
        pending = await made(stack)
        await set_setting(stack, OUTCOME, "pending")
        first = ok(await press_approve(stack, pending))
        assert view_of(first)["phase"] == "processing"
        done = ok(await verify(stack, pending))
        assert view_of(done)["phase"] == "succeeded" and len(await charges(stack)) == 1

    async def test_a_food_order_whose_payment_is_pending_is_followed_with_track_order(self, stack):
        card_id = await connect(stack, merchant=CHOWDECK)
        await link_chowdeck(stack, card_id)
        request = {
            "merchant_id": CHOWDECK,
            "lines": [{"offer_id": "v101-i5001"}],
            "fields": {},
            "idempotency_key": new_key(),
        }
        pending = await quote(stack, **request)
        await set_setting(stack, OUTCOME, "pending")
        assert view_of(ok(await press_approve(stack, pending)))["phase"] == "processing"
        await stack.db.execute("UPDATE sim_index_order SET status = 'completed'")
        assert view_of(ok(await verify(stack, pending)))["phase"] == "succeeded"
        assert "track_order" in await tools_called(stack)


class TestApprovalAndDisconnecting:
    async def test_disconnecting_between_the_approval_and_the_send_sends_nothing(self, stack):
        pending = await made(stack)
        card_id = (await stack.rows("SELECT id FROM index_attempt"))[0]["id"]
        with acting_for(ALICE), remembering_for(ALICE):
            await stack.merchants.authorise_approval(
                view_of(pending)["id"], pending["_meta"]["approvalToken"], 100_000, terms=_external_terms()
            )
        ok(await account(stack, "disconnect_account", card_id=card_id))
        done = ok(await verify(stack, pending))
        assert view_of(done)["phase"] == "failed" and "Nothing was sent" in view_of(done)["message"]
        assert await charges(stack) == [] and await zap(stack) == 5_000_000

    async def test_disconnecting_before_approving_refuses_the_approval_and_keeps_the_quote_open(self, stack):
        pending = await made(stack)
        card_id = (await stack.rows("SELECT id FROM index_attempt"))[0]["id"]
        ok(await account(stack, "disconnect_account", card_id=card_id))
        refused = await press_approve(stack, pending)
        assert "connect_account" in text_of(refused)
        assert (await stored(stack, view_of(pending)["id"]))["state"] == "open"

    async def test_an_approval_and_a_disconnect_together_charge_at_most_once_and_leave_a_clear_ending(
        self, stack
    ):
        pending = await made(stack)
        card_id = (await stack.rows("SELECT id FROM index_attempt"))[0]["id"]
        await asyncio.gather(
            press_approve(stack, pending), account(stack, "disconnect_account", card_id=card_id)
        )
        held = await stored(stack, view_of(pending)["id"])
        assert len(await charges(stack)) <= 1
        assert held["state"] in ("settled", "failed", "open", "approved")
        if held["state"] == "failed":
            assert await sim_orders(stack) == []


class TestOtherFundingIsKeptApart:
    async def test_the_wallet_cannot_approve_an_index_quote(self, stack):
        await fund(stack, 5_000_000, ALICE)
        pending = await made(stack)
        refused = await account(stack, "approve_quote", **approval(pending), funding="wallet")
        assert "FUNDING_MISMATCH" in text_of(refused)
        assert await charges(stack) == [] and await stack.count("wallet_entry") == 1

    async def test_the_checkout_cannot_approve_an_index_quote(self, stack):
        pending = await made(stack)
        refused = await account(stack, "approve_quote", **approval(pending), funding="checkout")
        assert "FUNDING_MISMATCH" in text_of(refused) and await charges(stack) == []

    async def test_an_ordinary_quote_cannot_be_approved_as_paid_by_index(self, stack):
        from tests.commerce_support import as_account, meal

        ordinary = await as_account(stack, "create_quote", **meal())
        refused = await account(stack, "approve_quote", **approval(ordinary), funding="external")
        assert "FUNDING_MISMATCH" in text_of(refused)
        assert (await stored(stack, view_of(ordinary)["id"]))["state"] == "open"

    async def test_the_claim_itself_refuses_a_quote_that_was_not_made_to_be_paid_by_index(self, stack):
        from checkout.errors import DomainError
        from tests.commerce_support import as_account, meal

        ordinary = await as_account(stack, "create_quote", **meal())
        view = view_of(ordinary)
        with acting_for(ALICE), remembering_for(ALICE):
            with pytest.raises(DomainError):
                await stack.merchants.authorise_approval(
                    view["id"], ordinary["_meta"]["approvalToken"], view["amount"]["kobo"], terms=_external_terms()
                )
        assert (await stored(stack, view["id"]))["state"] == "open"

    async def test_the_approval_token_is_bound_to_where_the_money_comes_from(self, stack):
        from checkout.commerce.binding import quote_digest

        pending = await made(stack)
        quote_id = view_of(pending)["id"]
        with acting_for(ALICE):
            row = await stack.ledger.get(quote_id)
        before = quote_digest(row)
        changed = row.details | {"index": {**row.details["index"], "arguments": {"amount_naira": 1}}}
        assert quote_digest(type(row)(**{**row.__dict__, "details": changed})) != before


def _external_terms():
    from checkout.flows.merchants import EXTERNAL_PAID

    return EXTERNAL_PAID
