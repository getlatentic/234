# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated checkout page and the payment webhook hold no owner: a person opens the page by holding an
unguessable reference. What they can do is bounded by that reference: a press changes that one transaction,
once, and the webhook names that one quote."""

import re

import pytest

from checkout.http import handle
from checkout.ids import new_quote_id, quote_id_of, transaction_reference
from tests.connector_support import approve_args, key, quote_of
from tests.support import ALICE, BOB, make_stack
from tests.test_webhook import RecordingNotifier

PAY = "paystack-pay"


async def approved_for(stack, owner, amount=250_000, said="2.5k"):
    made = await stack.call_as(
        owner, PAY, "create_payment_quote",
        amount_kobo=amount, amount_as_user_said=said, description="Lunch", merchant="Demo Kitchen",
        idempotency_key=key("checkout-owner"),
    )  # fmt: skip
    approved = await stack.call_as(owner, PAY, "approve_quote", **approve_args(made))
    return quote_of(made)["id"], quote_of(approved)["checkoutUrl"].rsplit("/", 1)[1]


async def press(stack, reference, button):
    return await handle(stack.app, "POST", f"/sim/checkout/{reference}/{button}", {}, b"")


async def phase_of(stack, owner, quote_id):
    seen = await stack.call_as(owner, PAY, "verify_quote", quote_id=quote_id)
    return quote_of(seen)["phase"]


class TestTheReference:
    def test_is_eighty_random_bits_that_nothing_predicts(self):
        ids = [new_quote_id() for _ in range(300)]
        assert len(set(ids)) == 300 and all(re.fullmatch(r"qt-[0-9a-f]{20}", i) for i in ids)
        for position in range(3, 23):
            assert len({i[position] for i in ids}) >= 8, "a position that hardly varies is not random"
        assert ids != sorted(ids) and ids != sorted(ids, reverse=True)

    def test_is_the_quote_id_and_an_attempt_and_names_its_quote_only(self):
        quote = new_quote_id()
        assert quote_id_of(transaction_reference(quote, 2)) == quote
        for foreign in ("ref-1", quote, f"{quote}-a", f"x{quote}-a1", f"{quote}-a1/../{quote}-a2"):
            assert quote_id_of(foreign) is None


class TestAPress:
    async def test_changes_the_one_transaction_it_names_and_no_other_owners(self):
        stack = make_stack()
        alices, alices_ref = await approved_for(stack, ALICE)
        bobs, bobs_ref = await approved_for(stack, BOB)
        page = await press(stack, alices_ref, "pay")
        assert page.status == 200 and "Paid" in page.body
        assert await phase_of(stack, ALICE, alices) == "succeeded"
        assert await phase_of(stack, BOB, bobs) == "awaiting_checkout"
        assert (await stack.app.paystack_sim.transaction(bobs_ref)).status == "abandoned"

    async def test_of_a_reference_nobody_holds_finds_nothing_and_makes_nothing(self):
        stack = make_stack()
        _, reference = await approved_for(stack, ALICE)
        guess = transaction_reference(new_quote_id(), 1)
        before = await stack.count("sim_transactions")
        for method, path in (("GET", guess), ("POST", f"{guess}/pay"), ("POST", f"{guess}/decline")):
            reply = await handle(stack.app, method, f"/sim/checkout/{path}", {}, b"")
            assert reply.status == 404
        assert await stack.count("sim_transactions") == before
        assert (await stack.app.paystack_sim.transaction(reference)).status == "abandoned"

    async def test_after_the_payment_is_final_changes_nothing_however_it_is_pressed(self):
        stack = make_stack()
        quote, reference = await approved_for(stack, ALICE)
        await press(stack, reference, "pay")
        for button in ("pay", "decline", "close"):
            await press(stack, reference, button)
        assert (await stack.app.paystack_sim.transaction(reference)).status == "success"
        assert await phase_of(stack, ALICE, quote) == "succeeded"

    async def test_of_a_decline_cannot_be_turned_into_a_payment_by_a_later_press(self):
        stack = make_stack()
        _, reference = await approved_for(stack, ALICE)
        await press(stack, reference, "decline")
        await press(stack, reference, "pay")
        assert (await stack.app.paystack_sim.transaction(reference)).status == "failed"

    async def test_of_a_paid_quote_does_not_touch_another_owners_allowance_or_show_them_the_quote(self):
        stack = make_stack()
        quote, reference = await approved_for(stack, ALICE, 3_000_000, "30k")
        await press(stack, reference, "pay")
        bobs = await stack.call_as(BOB, PAY, "get_quote_status", quote_id=quote)
        assert bobs["isError"] is True
        with_bob = await stack.call_as(
            BOB, PAY, "create_payment_quote",
            amount_kobo=5_000_000, amount_as_user_said="50k", description="x", merchant="y",
            idempotency_key=key("bob-full"),
        )  # fmt: skip
        assert quote_of(with_bob)["limits"]["remainingToday"] == "₦100,000"


class TestTheWebhook:
    def stack(self):
        stack = make_stack()
        notifier = RecordingNotifier()
        object.__setattr__(stack.app, "notifier", notifier)
        return stack, notifier

    async def test_names_the_one_quote_whose_transaction_was_pressed(self):
        stack, notifier = self.stack()
        alices, alices_ref = await approved_for(stack, ALICE)
        bobs, bobs_ref = await approved_for(stack, BOB)
        await press(stack, bobs_ref, "pay")
        await press(stack, alices_ref, "decline")
        assert notifier.moved == [bobs, alices]

    @pytest.mark.parametrize("button", ["pay", "decline"])
    async def test_is_sent_once_for_a_transaction_however_often_it_is_pressed(self, button):
        stack, notifier = self.stack()
        quote, reference = await approved_for(stack, ALICE)
        for _ in range(3):
            await press(stack, reference, button)
        assert notifier.moved == [quote]

    async def test_is_not_sent_for_a_reference_nobody_holds(self):
        stack, notifier = self.stack()
        await approved_for(stack, ALICE)
        await press(stack, transaction_reference(new_quote_id(), 1), "pay")
        assert notifier.moved == []
