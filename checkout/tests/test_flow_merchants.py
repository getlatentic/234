# SPDX-License-Identifier: AGPL-3.0-or-later
"""A purchase from a merchant of the directory, end to end (docs/commerce.md): the quote the server priced,
the approval bound to all of it, payment from the wallet or at the checkout, and the three outcomes of the
merchant's order with the money following each."""

import json
from dataclasses import replace

from checkout.commerce.binding import approval_subject, quote_digest
from checkout.commerce.directory import DirectoryProvider
from checkout.receipts import TIMES
from tests.commerce_support import (
    CONNECTOR,
    MEAL_KOBO,
    answer,
    approval,
    approved_and_paid,
    as_account,
    checked,
    fund,
    meal,
    quote,
    stored,
    water_bill,
)
from tests.connector_support import quote_of, text_of
from tests.support import ALICE, BOB, make_stack
from tests.wallet_support import entries, journal_of


class TestMakingAQuote:
    async def test_the_quote_is_the_servers_sum_with_every_line_fee_and_field_kept(self, stack):
        view = quote_of(await quote(stack))
        assert view["amount"] == {"kobo": MEAL_KOBO, "display": "₦11,000"}
        assert view["merchant"] == "Mama Put Yaba (simulated)"
        assert view["description"] == "2 x Jollof rice with fried chicken, 1 x Zobo, 500ml"
        d = view["details"]
        assert [(x["name"], x["quantity"], x["unit"], x["total"]) for x in d["lines"]] == [
            ("Jollof rice with fried chicken", 2, "₦4,500", "₦9,000"),
            ("Zobo, 500ml", 1, "₦800", "₦800"),
        ]
        assert d["fees"] == [{"label": "Delivery", "amount": "₦1,200"}] and d["subtotal"] == "₦9,800"
        assert d["fields"] == [{"label": "Delivery area", "value": "Yaba"}] and d["holder"] is None

    async def test_the_stored_copy_keeps_what_the_quote_used_when_the_offer_changes_later(self, stack):
        made = await quote(stack)
        await stack.db.execute("UPDATE offer SET price_kobo = 1000000 WHERE id = 'jollof-chicken'")
        view = quote_of(await stack.call(CONNECTOR, "track_order", quote_id=quote_of(made)["id"]))
        assert view["amount"]["kobo"] == MEAL_KOBO

    async def test_a_repeat_with_the_same_key_gives_the_same_quote_and_token(self, stack):
        arguments = meal()
        first = await stack.call(CONNECTOR, "create_quote", **arguments)
        again = await stack.call(CONNECTOR, "create_quote", **arguments)
        assert quote_of(again)["id"] == quote_of(first)["id"]
        assert again["_meta"]["approvalToken"] == first["_meta"]["approvalToken"]
        assert await stack.count("quotes") == 1

    async def test_a_repeat_after_the_price_changed_still_gives_the_first_quote(self, stack):
        arguments = meal()
        first = await stack.call(CONNECTOR, "create_quote", **arguments)
        await stack.db.execute("UPDATE offer SET price_kobo = 500000 WHERE id = 'zobo'")
        again = await stack.call(CONNECTOR, "create_quote", **arguments)
        assert (
            quote_of(again)["id"] == quote_of(first)["id"] and quote_of(again)["amount"]["kobo"] == MEAL_KOBO
        )

    async def test_the_same_key_for_a_different_request_is_a_conflict(self, stack):
        arguments = meal()
        await stack.call(CONNECTOR, "create_quote", **arguments)
        for changed in (
            {"lines": [{"offer_id": "zobo", "quantity": 1}]},
            {"fields": {"area": "Ikoyi"}},
            {"merchant_id": "lagosmed-pharmacy"},
        ):
            result = await stack.call(CONNECTOR, "create_quote", **{**arguments, **changed})
            assert text_of(result).startswith("IDEMPOTENCY_CONFLICT"), changed
        assert await stack.count("quotes") == 1

    async def test_the_same_lines_in_another_order_or_split_are_the_same_request(self, stack):
        a = meal(lines=[{"offer_id": "zobo"}, {"offer_id": "jollof-chicken", "quantity": 2}])
        b = {
            **a,
            "lines": [
                {"offer_id": "jollof-chicken", "quantity": 1},
                {"offer_id": "zobo"},
                {"offer_id": "jollof-chicken"},
            ],
        }
        first = await stack.call(CONNECTOR, "create_quote", **a)
        again = await stack.call(CONNECTOR, "create_quote", **b)
        assert quote_of(again)["id"] == quote_of(first)["id"]

    async def test_an_amount_without_lines_is_for_the_merchants_one_offer_paid_for_any_amount(self, stack):
        check = await checked(stack)
        arguments = {**water_bill(check), "lines": []}
        made = await stack.call(CONNECTOR, "create_quote", **arguments)
        d = quote_of(made)["details"]
        assert [(x["name"], x["total"]) for x in d["lines"]] == [("Transit card top-up", "₦5,000")]
        by_hand = await stack.call(
            CONNECTOR, "create_quote", **{**water_bill(check), "idempotency_key": "other-key-01"}
        )
        assert quote_of(by_hand)["amount"]["kobo"] == quote_of(made)["amount"]["kobo"]

    async def test_no_lines_and_no_amount_or_no_single_offer_for_an_amount_is_refused(self, stack):
        check = await checked(stack)
        none = {**water_bill(check), "lines": [], "amount_kobo": None, "amount_as_user_said": None}
        assert text_of(await stack.call(CONNECTOR, "create_quote", **none)).startswith("INVALID_INPUT")
        shop = {**meal(), "lines": [], "amount_kobo": 500_000, "amount_as_user_said": "5000"}
        refused = await stack.call(CONNECTOR, "create_quote", **shop)
        assert text_of(refused).startswith("INVALID_INPUT") and "Pass lines naming the offer" in text_of(
            refused
        )
        await stack.db.execute("UPDATE offer SET available = 0 WHERE id = 'card-topup'")
        unavailable = await stack.call(CONNECTOR, "create_quote", **{**water_bill(check), "lines": []})
        assert text_of(unavailable).startswith("INVALID_INPUT")
        assert await stack.count("quotes") == 0

    async def test_an_amount_is_checked_against_the_persons_words(self, stack):
        check = await checked(stack)
        for said, code in (("4000", "AMOUNT_MISMATCH"), ("lots", "AMOUNT_UNCLEAR"), (None, "AMOUNT_UNCLEAR")):
            result = await stack.call(
                CONNECTOR, "create_quote", **water_bill(check, amount_as_user_said=said)
            )
            assert text_of(result).startswith(code), said
        assert await stack.count("quotes") == 0
        made = await stack.call(CONNECTOR, "create_quote", **water_bill(check, amount_as_user_said="₦5,000"))
        assert quote_of(made)["amount"]["kobo"] == 500_000

    async def test_an_amount_outside_the_merchants_limits_is_refused_and_nothing_is_quoted(self, stack):
        check = await checked(stack)
        for amount, said in ((10_000, "100"), (5_100_000, "51000")):
            result = await stack.call(
                CONNECTOR,
                "create_quote",
                **water_bill(check, amount_kobo=amount, amount_as_user_said=said),
            )
            assert text_of(result).startswith("AMOUNT_OUT_OF_LIMITS"), amount
        assert await stack.count("quotes") == 0

    async def test_the_persons_limits_still_apply(self):
        stack = make_stack(per_payment_limit_kobo=1_000_000)
        result = await quote(stack)
        assert text_of(result).startswith("LIMIT_PER_PAYMENT") and await stack.count("quotes") == 0

    async def test_every_refusal_and_every_quote_is_audited(self, stack):
        await quote(stack)
        await stack.call(CONNECTOR, "create_quote", **meal(merchant_id="dstv"))
        log = "\n".join(stack.audit_lines)
        assert '"quote.created"' in log and '"merchant_id": "mama-put-yaba"' in log


class TestTheApprovalIsBoundToTheQuote:
    async def test_the_token_is_the_ledgers_hmac_over_the_quote_and_a_digest_of_its_terms(self, stack):
        made = await quote(stack)
        quote_row = await stack.ledger.get(quote_of(made)["id"])
        assert made["_meta"]["approvalToken"] == stack.ledger.approval_token(approval_subject(quote_row))
        assert made["_meta"]["approvalToken"] != stack.ledger.approval_token(quote_row.id)

    async def test_the_token_of_the_quotes_id_alone_approves_nothing(self, stack):
        made = await quote(stack)
        quote_id = quote_of(made)["id"]
        plain = stack.ledger.approval_token(quote_id)
        result = await stack.call(CONNECTOR, "approve_quote", **approval(made, approval_token=plain))
        assert text_of(result).startswith("APPROVAL_DENIED")
        assert (await stack.ledger.get(quote_id)).state == "open"

    async def test_one_quotes_token_does_not_approve_another(self, stack):
        first, second = await quote(stack), await quote(stack, fields={"area": "Ikoyi"})
        result = await stack.call(
            CONNECTOR, "approve_quote", **approval(second, approval_token=first["_meta"]["approvalToken"])
        )
        assert text_of(result).startswith("APPROVAL_DENIED")

    async def test_nor_does_a_token_decline_a_quote_it_was_not_made_for(self, stack):
        first, second = await quote(stack), await quote(stack, fields={"area": "Ikoyi"})
        result = await stack.call(
            CONNECTOR,
            "decline_quote",
            quote_id=quote_of(second)["id"],
            approval_token=first["_meta"]["approvalToken"],
        )
        assert text_of(result).startswith("APPROVAL_DENIED")
        declined = await stack.call(
            CONNECTOR,
            "decline_quote",
            quote_id=quote_of(first)["id"],
            approval_token=first["_meta"]["approvalToken"],
        )
        assert quote_of(declined)["phase"] == "declined"

    async def test_the_digest_changes_with_the_merchant_lines_fees_fields_holder_total_or_expiry(self, stack):
        stored = await stack.ledger.get(quote_of(await quote(stack))["id"])
        base = quote_digest(stored)
        changes = {
            "merchant": replace(stored, details={**stored.details, "merchantId": "other"}),
            "lines": replace(stored, details={**stored.details, "lines": stored.details["lines"][:1]}),
            "fees": replace(stored, details={**stored.details, "fees": []}),
            "fields": replace(stored, details={**stored.details, "fields": []}),
            "holder": replace(stored, details={**stored.details, "holder": "SOMEONE"}),
            "total": replace(stored, amount_kobo=stored.amount_kobo - 1),
            "expiry": replace(stored, expires_at=stored.expires_at + 1),
        }
        for what, changed in changes.items():
            assert quote_digest(changed) != base, what
            assert approval_subject(changed) != approval_subject(stored), what

    async def test_a_quote_no_longer_matching_its_token_cannot_be_approved(self, stack, monkeypatch):
        """If the stored terms ever differ from what the token was made for, the approval is denied."""
        made = await quote(stack)
        stored = await stack.ledger.get(quote_of(made)["id"])
        tampered = replace(stored, amount_kobo=stored.amount_kobo - 100)

        async def get_tampered(self, quote_id):
            return tampered

        monkeypatch.setattr(type(stack.ledger), "get", get_tampered)
        assert not await stack.merchants.token_is_valid(stored.id, made["_meta"]["approvalToken"])

    async def test_the_card_must_show_the_amount_the_server_holds(self, stack):
        made = await quote(stack)
        result = await stack.call(CONNECTOR, "approve_quote", **approval(made, displayed_amount_kobo=1))
        assert text_of(result).startswith("AMOUNT_MISMATCH")


class TestPayingAtTheCheckout:
    async def test_approved_paid_and_delivered_with_a_receipt_of_every_line(self, stack):
        made = await quote(stack)
        done = quote_of(await approved_and_paid(stack, made))
        assert (done["phase"], done["poll"]) == ("succeeded", False)
        labels = [(row["label"], row["value"]) for row in done["receipt"]["lines"]]
        assert done["receipt"]["title"] == "Order delivered"
        assert (f"2 {TIMES} Jollof rice with fried chicken", "₦9,000") in labels and (
            "Delivery",
            "₦1,200",
        ) in labels
        assert ("Delivery area", "Yaba") in labels

    async def test_the_checkout_is_for_the_servers_total(self, stack):
        made = await quote(stack)
        approved = quote_of(await stack.call(CONNECTOR, "approve_quote", **approval(made)))
        assert approved["phase"] == "awaiting_checkout" and approved["checkoutUrl"]
        (paid,) = await stack.rows("SELECT amount_kobo FROM sim_transactions")
        assert paid["amount_kobo"] == MEAL_KOBO

    async def test_a_checked_account_shows_its_holder_on_the_card_and_the_receipt(self, stack):
        made = await stack.call(CONNECTOR, "create_quote", **water_bill(await checked(stack)))
        assert quote_of(made)["details"]["holder"] == "ADEBAYO OLUWASEUN FOLA"
        done = quote_of(await approved_and_paid(stack, made))
        assert ("Account holder", "ADEBAYO OLUWASEUN FOLA") in [
            (row["label"], row["value"]) for row in done["receipt"]["lines"]
        ]

    async def test_a_checkout_that_failed_ends_the_quote_and_the_merchant_is_never_asked(self, stack):
        made = await quote(stack)
        approved = quote_of(await stack.call(CONNECTOR, "approve_quote", **approval(made)))
        await stack.complete_checkout(approved["checkoutUrl"], "failed")
        assert (
            quote_of(await stack.call(CONNECTOR, "verify_quote", quote_id=approved["id"]))["phase"]
            == "failed"
        )
        assert await stack.count("sim_merchant_order") == 0


class TestPayingFromTheWallet:
    async def test_the_wallet_pays_the_servers_total_and_the_order_is_delivered_at_once(self, stack):
        await fund(stack, 2_000_000, ALICE)
        made = await as_account(stack, "create_quote", **meal())
        assert quote_of(made)["wallet"] == {"covers": True}
        done = quote_of(await as_account(stack, "approve_quote", **approval(made, funding="wallet")))
        assert done["phase"] == "succeeded" and done["checkoutUrl"] is None
        assert await journal_of(stack).balance(ALICE) == 2_000_000 - MEAL_KOBO
        (hold,) = await entries(stack, "spend")
        assert (hold["ref"], hold["amount_kobo"]) == (done["id"], MEAL_KOBO)
        assert await stack.count("sim_transactions") == 0

    async def test_a_wallet_that_does_not_cover_it_takes_nothing_and_offers_nothing(self, stack):
        await fund(stack, MEAL_KOBO - 1, ALICE)
        made = await as_account(stack, "create_quote", **meal())
        assert "wallet" not in quote_of(made)
        result = await as_account(stack, "approve_quote", **approval(made, funding="wallet"))
        assert text_of(result).startswith("WALLET_SHORT")
        assert await entries(stack, "spend") == []
        assert (await stored(stack, quote_of(made)["id"]))["state"] == "open"

    async def test_a_person_who_asked_for_the_wallet_is_told_whether_it_covers_and_never_its_balance(
        self, stack
    ):
        await fund(stack, MEAL_KOBO + 123, ALICE)
        covered = text_of(await as_account(stack, "create_quote", **meal(from_wallet=True)))
        assert "Their wallet covers this" in covered and "123" not in covered
        dear = meal(from_wallet=True, lines=[{"offer_id": "catfish-pepper-soup", "quantity": 3}])
        assert "Their wallet does NOT cover this" in text_of(await as_account(stack, "create_quote", **dear))

    async def test_a_visitor_has_no_wallet_to_pay_from(self, stack):
        await fund(stack, 2_000_000, ALICE)
        made = await quote(stack, owner=ALICE)
        assert "wallet" not in quote_of(made)
        refused = await stack.call_as(ALICE, CONNECTOR, "approve_quote", **approval(made, funding="wallet"))
        assert text_of(refused).startswith("WALLET_ACCOUNT_ONLY") and await entries(stack, "spend") == []

    async def test_a_quote_approved_twice_from_the_wallet_is_paid_once(self, stack):
        await fund(stack, 3_000_000, ALICE)
        made = await as_account(stack, "create_quote", **meal())
        first = await as_account(stack, "approve_quote", **approval(made, funding="wallet"))
        second = await as_account(stack, "approve_quote", **approval(made, funding="wallet"))
        assert quote_of(first)["phase"] == quote_of(second)["phase"] == "succeeded"
        assert len(await entries(stack, "spend")) == 1


async def paid_from_wallet(stack, outcome: str | None = None):
    """A meal paid from Alice's funded wallet, the merchant set to `outcome` first: the quote id and view."""
    await fund(stack, 2_000_000, ALICE)
    made = await as_account(stack, "create_quote", **meal())
    quote_id = quote_of(made)["id"]
    if outcome:
        await answer(stack, quote_id, outcome)
    approved = quote_of(await as_account(stack, "approve_quote", **approval(made, funding="wallet")))
    return quote_id, approved


class TestTheThreeOutcomes:
    async def test_a_merchant_that_delivers_settles_the_quote_once(self, stack):
        quote_id, approved = await paid_from_wallet(stack)
        assert approved["phase"] == "succeeded"
        for _ in range(3):
            assert (
                quote_of(await as_account(stack, "verify_quote", quote_id=quote_id))["phase"] == "succeeded"
            )
        assert await stack.count("sim_merchant_order") == 1
        assert len([line for line in stack.audit_lines if '"fulfilment.delivered"' in line]) == 1

    async def test_a_merchant_that_has_not_answered_is_pending_and_asked_again_never_ordered_again(
        self, stack, monkeypatch
    ):
        placed = []
        real = DirectoryProvider.fulfil

        async def counting(self, quote):
            placed.append(quote.id)
            return await real(self, quote)

        monkeypatch.setattr(DirectoryProvider, "fulfil", counting)
        quote_id, pending = await paid_from_wallet(stack, "pending")
        assert (pending["phase"], pending["poll"]) == ("processing", True)
        for _ in range(3):
            assert (
                quote_of(await as_account(stack, "verify_quote", quote_id=quote_id))["phase"] == "processing"
            )
        assert placed == [quote_id], "the order was placed once"
        assert (await stored(stack, quote_id))["progress"]["fulfilment"]["attempts"] == 4

    async def test_a_pending_order_the_merchant_then_delivers_is_settled_by_the_recheck(self, stack):
        quote_id, pending = await paid_from_wallet(stack, "pending")
        assert pending["phase"] == "processing"
        moved = json.loads((await answer(stack, quote_id, "delivered")).body)
        assert moved == {"outcome": "delivered", "asked": True}
        await stack.run_jobs()
        assert (await stored(stack, quote_id))["state"] == "settled"

    async def test_a_merchant_that_refuses_gives_the_wallet_its_money_back_once(self, stack):
        quote_id, failed = await paid_from_wallet(stack, "failed")
        assert failed["phase"] == "failed"
        assert failed["message"].startswith(
            "Mama Put Yaba (simulated) did not deliver: The merchant could not fill the order."
        )
        assert "₦11,000 is back in the wallet" in failed["message"]
        assert await journal_of(stack).balance(ALICE) == 2_000_000
        for _ in range(3):
            await as_account(stack, "verify_quote", quote_id=quote_id)
        (refund,) = await entries(stack, "refund")
        assert (refund["ref"], refund["amount_kobo"]) == (quote_id, MEAL_KOBO)
        assert await journal_of(stack).balance(ALICE) == 2_000_000

    async def test_a_merchant_that_refuses_a_checkout_payment_owes_a_paystack_refund(self, stack):
        made = await quote(stack)
        await answer(stack, quote_of(made)["id"], "failed")
        done = quote_of(await approved_and_paid(stack, made))
        assert done["phase"] == "attention" and done["refund"] == {
            "title": "Refunding ₦11,000",
            "state": None,
        }
        assert "refund.due" in "\n".join(stack.audit_lines)
        await stack.run_jobs()
        (refund,) = await stack.rows("SELECT state, amount_kobo FROM quote_refund")
        assert (refund["state"], refund["amount_kobo"]) == ("sent", MEAL_KOBO)

    async def test_a_decided_merchant_does_not_change_its_answer(self, stack):
        quote_id, approved = await paid_from_wallet(stack)
        late = json.loads((await answer(stack, quote_id, "failed")).body)
        assert approved["phase"] == "succeeded" and late["outcome"] == "delivered"
        assert (await stored(stack, quote_id))["state"] == "settled"

    async def test_the_test_route_knows_only_this_connectors_quotes_and_three_answers(self, stack):
        made = await quote(stack)
        assert (await answer(stack, quote_of(made)["id"], "lost")).status == 400
        assert (await answer(stack, "qt-00000000000000000000", "failed")).status == 404
        other = await stack.call(
            "paystack-pay", "create_payment_quote", amount_kobo=100_000, amount_as_user_said="1000",
            description="Lunch", merchant="Shop", idempotency_key="other-key-0002",
        )  # fmt: skip
        assert (await answer(stack, quote_of(other)["id"], "failed")).status == 404

    async def test_a_provider_that_breaks_lets_go_of_the_step_so_the_next_check_goes_on(
        self, stack, monkeypatch
    ):
        real, broke = DirectoryProvider.fulfil, []

        async def breaks_once(self, quote):
            if not broke:
                broke.append(quote.id)
                raise RuntimeError("unexpected")
            return await real(self, quote)

        monkeypatch.setattr(DirectoryProvider, "fulfil", breaks_once)
        await fund(stack, 2_000_000, ALICE)
        made = await as_account(stack, "create_quote", **meal())
        quote_id = quote_of(made)["id"]
        broken = await as_account(stack, "approve_quote", **approval(made, funding="wallet"))
        assert broken["isError"] is True and broke == [quote_id]
        assert quote_of(await as_account(stack, "verify_quote", quote_id=quote_id))["phase"] == "succeeded"


class TestWhatCannotBeApproved:
    async def test_an_expired_quote_takes_nothing_from_the_wallet(self, stack):
        await fund(stack, 2_000_000, ALICE)
        made = await as_account(stack, "create_quote", **meal())
        stack.clock.advance(601)
        result = await as_account(stack, "approve_quote", **approval(made, funding="wallet"))
        assert text_of(result).startswith("QUOTE_EXPIRED")
        assert await journal_of(stack).balance(ALICE) == 2_000_000

    async def test_a_declined_quote_cannot_be_approved(self, stack):
        made = await quote(stack)
        token = made["_meta"]["approvalToken"]
        await stack.call(CONNECTOR, "decline_quote", quote_id=quote_of(made)["id"], approval_token=token)
        result = await stack.call(CONNECTOR, "approve_quote", **approval(made))
        assert text_of(result).startswith("QUOTE_NOT_OPEN")

    async def test_a_quote_is_not_visible_to_another_owner(self, stack):
        made = await quote(stack, owner=ALICE)
        for tool in ("track_order", "verify_quote", "approve_quote"):
            arguments = approval(made) if tool == "approve_quote" else {"quote_id": quote_of(made)["id"]}
            assert (await stack.call_as(BOB, CONNECTOR, tool, **arguments))["isError"] is True
