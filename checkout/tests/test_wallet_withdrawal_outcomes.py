# SPDX-License-Identifier: AGPL-3.0-or-later
"""What becomes of a withdrawal's transfer (wallet/withdrawal_outcome.py): success settles it, failed or
reversed gives the money back once, and anything undecided waits for a Paystack event or the minute re-check,
under the one reference it was sent with."""

import pytest

from checkout.paystack.api import PaystackError, TransferOutcome
from tests.support import ALICE, PaystackOverride
from tests.withdrawal_support import (
    approved,
    balance,
    funded,
    kinds,
    paystack_event,
    set_transfer,
    started,
    state_of,
    with_paystack,
    withdrawals,
)

AMOUNT = 2_000_000


def paystack_of(stack):
    return stack.app.contexts["send-money"].paystack


async def pending_send(stack):
    """A withdrawal Paystack took but has not settled: the transfer exists and reads `pending`."""
    inner = paystack_of(stack)

    async def queued(request):
        sent = await inner.initiate_transfer(request)
        await stack.db.execute(
            "UPDATE sim_transfers SET status = 'pending' WHERE reference = ?", sent.reference
        )
        return TransferOutcome("pending", sent.transfer_code, sent.reference, sent.amount_kobo)

    with_paystack(stack, PaystackOverride(inner, initiate_transfer=queued))
    await funded(stack)
    return await approved(stack, await started(stack, AMOUNT))


async def unanswered_send(stack, reached: bool):
    """A send whose answer was lost: `reached` says whether Paystack made the transfer anyway."""
    inner = paystack_of(stack)
    paystack = PaystackOverride(inner)

    async def lost(request):
        if reached:
            await inner.initiate_transfer(request)
        raise PaystackError("Paystack could not be reached.", retryable=True)

    paystack._replacements["initiate_transfer"] = lost
    with_paystack(stack, paystack)
    await funded(stack)
    withdrawal = await approved(stack, await started(stack, AMOUNT))
    paystack._replacements.pop("initiate_transfer")
    return withdrawal, paystack


async def sweep(stack, after_seconds: float = 60) -> None:
    stack.clock.advance(after_seconds)
    await stack.app.background.minute()
    await stack.run_jobs()


class TestDecidedAtOnce:
    async def test_success_settles_it_and_the_money_stays_out(self, stack):
        await funded(stack)
        done = await approved(stack, await started(stack, AMOUNT))
        assert (done.state, done.transfer_status, done.decided_at is not None) == (
            "succeeded",
            "success",
            True,
        )
        assert await balance(stack) == 10_000_000 - AMOUNT

    async def test_a_transfer_paystack_refuses_fails_and_gives_the_money_back(self, stack):
        async def refused(request):
            raise PaystackError("Insufficient balance", retryable=False, http_status=400)

        with_paystack(stack, PaystackOverride(paystack_of(stack), initiate_transfer=refused))
        await funded(stack)
        done = await approved(stack, await started(stack, AMOUNT))
        assert done.state == "failed"
        assert await kinds(stack) == ["fund", "withdraw", "withdraw_back"]
        assert await balance(stack) == 10_000_000

    async def test_a_refusal_for_a_reference_paystack_already_holds_is_not_a_failure(self, stack):
        inner = paystack_of(stack)

        async def duplicate(request):
            await inner.initiate_transfer(request)
            raise PaystackError("Duplicate Transaction Reference", retryable=False, http_status=400)

        with_paystack(stack, PaystackOverride(inner, initiate_transfer=duplicate))
        await funded(stack)
        done = await approved(stack, await started(stack, AMOUNT))
        assert done.state == "succeeded" and await kinds(stack) == ["fund", "withdraw"]


class TestUndecided:
    async def test_pending_stays_sent_with_the_money_out(self, stack):
        withdrawal = await pending_send(stack)
        assert (withdrawal.state, withdrawal.transfer_status) == ("sent", "pending")
        assert await balance(stack) == 10_000_000 - AMOUNT

    async def test_then_paystacks_success_event_settles_it(self, stack):
        withdrawal = await pending_send(stack)
        await set_transfer(stack, withdrawal, "success")
        answer = await paystack_event(stack, withdrawal, "transfer.success")
        assert answer.status == 200 and await state_of(stack, withdrawal) == "sent"
        await stack.run_jobs()
        assert await state_of(stack, withdrawal) == "succeeded"
        assert await kinds(stack) == ["fund", "withdraw"]

    async def test_then_a_failure_found_by_the_minute_gives_the_money_back(self, stack):
        withdrawal = await pending_send(stack)
        await set_transfer(stack, withdrawal, "failed")
        await sweep(stack)
        assert await state_of(stack, withdrawal) == "failed"
        assert await balance(stack) == 10_000_000

    async def test_the_minute_waits_before_asking(self, stack):
        withdrawal = await pending_send(stack)
        await set_transfer(stack, withdrawal, "success")
        await sweep(stack, after_seconds=5)
        assert await state_of(stack, withdrawal) == "sent"

    async def test_an_event_paystack_did_not_sign_changes_nothing(self, stack):
        from checkout.http import handle
        from tests.withdrawal_support import transfer_event

        withdrawal = await pending_send(stack)
        await set_transfer(stack, withdrawal, "failed")
        body = transfer_event(withdrawal, "transfer.failed")
        answer = await handle(stack.app, "POST", "/hooks/paystack", {"x-paystack-signature": "f" * 128}, body)
        await stack.run_jobs()
        assert answer.status == 401 and await state_of(stack, withdrawal) == "sent"

    async def test_an_event_says_nothing_paystack_does_not_confirm(self, stack):
        withdrawal = await pending_send(stack)
        await paystack_event(stack, withdrawal, "transfer.failed")
        await stack.run_jobs()
        assert await state_of(stack, withdrawal) == "sent" and await kinds(stack) == ["fund", "withdraw"]


class TestNeverSentTwice:
    async def test_a_lost_answer_is_asked_about_and_found_never_sent_again(self, stack):
        withdrawal, paystack = await unanswered_send(stack, reached=True)
        assert withdrawal.state == "sent" and withdrawal.transfer_code is None
        await sweep(stack)
        assert await state_of(stack, withdrawal) == "succeeded"
        assert paystack.calls["initiate_transfer"] == 1
        assert await stack.count("sim_transfers") == 1

    async def test_a_send_that_never_arrived_is_sent_once_under_the_same_reference(self, stack):
        withdrawal, paystack = await unanswered_send(stack, reached=False)
        sent: list[str] = []
        inner = paystack_of(stack)

        async def recorded(request):
            sent.append(request.reference)
            return await inner.initiate_transfer(request)

        paystack._replacements["initiate_transfer"] = recorded
        await sweep(stack)
        await sweep(stack)
        assert sent == [withdrawal.id]
        assert await state_of(stack, withdrawal) == "succeeded"
        assert [r["reference"] for r in await stack.rows("SELECT reference FROM sim_transfers")] == [
            withdrawal.id
        ]

    async def test_a_send_still_in_flight_is_not_sent_again_by_the_re_check(self, stack):
        withdrawal, paystack = await unanswered_send(stack, reached=False)
        await stack.db.execute(
            "UPDATE wallet_withdrawal SET sending_since = ? WHERE id = ?",
            stack.clock.now() + 60_000,
            withdrawal.id,
        )
        await sweep(stack)
        assert paystack.calls["initiate_transfer"] == 1 and await state_of(stack, withdrawal) == "sent"

    async def test_a_transfer_paystack_answered_for_is_never_sent_again(self, stack):
        withdrawal = await pending_send(stack)
        await stack.db.execute("DELETE FROM sim_transfers WHERE reference = ?", withdrawal.id)
        await sweep(stack)
        assert await stack.count("sim_transfers") == 0 and await state_of(stack, withdrawal) == "sent"


class TestReversed:
    async def test_a_success_that_comes_back_gives_the_money_back_once(self, stack):
        await funded(stack)
        withdrawal = await approved(stack, await started(stack, AMOUNT))
        await set_transfer(stack, withdrawal, "reversed")
        for _ in range(2):
            await paystack_event(stack, withdrawal, "transfer.reversed")
        await stack.run_jobs()
        await stack.run_jobs()
        assert await state_of(stack, withdrawal) == "reversed"
        assert await kinds(stack) == ["fund", "withdraw", "withdraw_back"]
        assert await balance(stack) == 10_000_000

    @pytest.mark.parametrize("end", ["failed", "reversed"])
    async def test_a_decided_withdrawal_stays_decided(self, stack, end):
        withdrawal = await pending_send(stack)
        await set_transfer(stack, withdrawal, end)
        await withdrawals(stack).outcomes.recheck(withdrawal.id)
        await set_transfer(stack, withdrawal, "success")
        await withdrawals(stack).outcomes.recheck(withdrawal.id)
        assert await state_of(stack, withdrawal) == end
        assert (await kinds(stack)).count("withdraw_back") == 1

    async def test_a_success_later_read_as_failed_stays_settled_only_a_reversal_gives_back(self, stack):
        await funded(stack)
        withdrawal = await approved(stack, await started(stack, AMOUNT))
        await set_transfer(stack, withdrawal, "failed")
        await withdrawals(stack).outcomes.recheck(withdrawal.id)
        assert await state_of(stack, withdrawal) == "succeeded"
        assert await kinds(stack) == ["fund", "withdraw"]

    async def test_the_database_keeps_a_final_state_final(self, stack):
        await funded(stack)
        withdrawal = await approved(stack, await started(stack, AMOUNT))
        await set_transfer(stack, withdrawal, "reversed")
        await withdrawals(stack).outcomes.recheck(withdrawal.id)
        with pytest.raises(Exception, match="stays decided"):
            await stack.db.execute(
                "UPDATE wallet_withdrawal SET state = 'succeeded' WHERE id = ?", withdrawal.id
            )

    async def test_a_withdrawal_whose_amount_paystack_reports_otherwise_stays_undecided(self, stack):
        inner = paystack_of(stack)

        async def other_amount(request):
            sent = await inner.initiate_transfer(request)
            return TransferOutcome("success", sent.transfer_code, sent.reference, sent.amount_kobo + 1)

        with_paystack(stack, PaystackOverride(inner, initiate_transfer=other_amount))
        await funded(stack)
        done = await approved(stack, await started(stack, AMOUNT))
        assert done.state == "sent"
        assert any('"withdrawal.mismatch"' in line for line in stack.audit_lines)


async def test_the_owner_never_changes_on_the_way(stack):
    await funded(stack)
    withdrawal = await approved(stack, await started(stack, AMOUNT))
    owners = await stack.rows("SELECT DISTINCT owner FROM wallet_entry")
    assert [row["owner"] for row in owners] == [ALICE] and withdrawal.owner == ALICE
