# SPDX-License-Identifier: AGPL-3.0-or-later
"""Starting and approving a withdrawal (wallet/withdrawals.py): the account resolved by the bank, nothing
taken until the person confirms its name on the card, and every rule held by the one statement that takes
the money: the token, the name, the amount shown, the time, the caps, the balance, the freeze, the block."""

import pytest

from checkout.errors import DomainError
from checkout.wallet.withdrawal_block import withdrawals_blocked
from tests.support import ALICE, BOB
from tests.withdrawal_support import (
    ACCOUNT,
    NAME,
    approved,
    balance,
    funded,
    kinds,
    set_transfer,
    started,
    state_of,
    withdrawals,
)


async def code_of(work) -> str:
    try:
        await work
    except DomainError as error:
        return error.code
    return "none"


async def block(stack, owner=ALICE, lifted_at=None) -> None:
    await stack.db.execute(
        "INSERT INTO wallet_withdrawal_block (owner, reason, ref, created_at, lifted_at) "
        "VALUES (?, 'dispute', 'dp-1', ?, ?)",
        owner,
        stack.clock.now(),
        lifted_at,
    )


class TestStarting:
    async def test_the_bank_names_the_account_and_nothing_is_taken(self, stack):
        await funded(stack)
        withdrawal = await started(stack)
        assert (withdrawal.state, withdrawal.account_name, withdrawal.amount_kobo) == (
            "open",
            NAME,
            2_000_000,
        )
        assert (withdrawal.account_number, withdrawal.bank_code) == (ACCOUNT, "058")
        assert withdrawal.recipient_code.startswith("RCP_")
        assert await balance(stack) == 10_000_000 and await kinds(stack) == ["fund"]

    async def test_the_audit_holds_the_account_masked_never_whole(self, stack):
        await funded(stack)
        await started(stack)
        assert ACCOUNT not in "\n".join(stack.audit_lines)
        assert "******6789" in "\n".join(stack.audit_lines)

    async def test_an_account_the_bank_cannot_resolve_opens_nothing(self, stack):
        await funded(stack)
        assert await code_of(started(stack, account="9999000000")) == "PROVIDER_ERROR"
        assert await stack.count("wallet_withdrawal") == 0

    @pytest.mark.parametrize(
        ("amount", "code"),
        [(5_000_001, "WITHDRAWAL_CAP"), (10_000_001, "WITHDRAWAL_CAP"), (5_000_000, "none")],
    )
    async def test_one_withdrawal_is_at_most_the_cap(self, stack, amount, code):
        await funded(stack, 20_000_000)
        assert await code_of(started(stack, amount)) == code

    async def test_more_than_the_balance_is_refused_before_any_bank_is_asked(self, stack):
        await funded(stack, 1_000_000)
        assert await code_of(started(stack, 1_000_100)) == "WALLET_SHORT"
        assert await stack.count("sim_recipients") == 0

    async def test_a_frozen_wallet_starts_none(self, stack):
        await funded(stack)
        await withdrawals(stack).journal.set_frozen(ALICE, True)
        assert await code_of(started(stack)) == "WALLET_FROZEN"

    async def test_a_visitor_without_a_wallet_starts_none(self, stack):
        assert await code_of(started(stack, owner=BOB)) == "WALLET_NONE"


class TestApproving:
    async def test_withdraw_takes_the_money_and_pays_the_account(self, stack):
        await funded(stack)
        done = await approved(stack, await started(stack))
        assert done.state == "succeeded" and done.name_confirmed_at is not None
        assert await balance(stack) == 8_000_000
        assert await kinds(stack) == ["fund", "withdraw"]
        transfers = await stack.rows("SELECT * FROM sim_transfers")
        assert [(t["reference"], t["amount_kobo"]) for t in transfers] == [(done.id, 2_000_000)]

    async def test_a_token_for_another_withdrawal_approves_nothing(self, stack):
        await funded(stack)
        one, two = await started(stack), await started(stack)
        token = withdrawals(stack).token(two.id)
        refused = withdrawals(stack).approve(ALICE, one.id, token, one.amount_kobo, one.account_name)
        assert await code_of(refused) == "WITHDRAWAL_DENIED"
        assert await kinds(stack) == ["fund"]

    async def test_a_name_other_than_the_banks_takes_nothing(self, stack):
        await funded(stack)
        withdrawal = await started(stack)
        assert await code_of(approved(stack, withdrawal, name="ADA LOVELACE")) == "NAME_NOT_CONFIRMED"
        assert await kinds(stack) == ["fund"] and await state_of(stack, withdrawal) == "open"

    async def test_an_amount_other_than_the_one_shown_takes_nothing(self, stack):
        await funded(stack)
        withdrawal = await started(stack)
        token = withdrawals(stack).token(withdrawal.id)
        refused = withdrawals(stack).approve(ALICE, withdrawal.id, token, 2_000_100, NAME)
        assert await code_of(refused) == "AMOUNT_MISMATCH"
        assert await kinds(stack) == ["fund"]

    async def test_someone_elses_withdrawal_is_not_theirs_to_approve(self, stack):
        await funded(stack)
        await funded(stack, owner=BOB)
        withdrawal = await started(stack)
        token = withdrawals(stack).token(withdrawal.id)
        refused = withdrawals(stack).approve(BOB, withdrawal.id, token, withdrawal.amount_kobo, NAME)
        assert await code_of(refused) == "WITHDRAWAL_NOT_FOUND"
        assert await kinds(stack) == ["fund"] and await kinds(stack, BOB) == ["fund"]

    async def test_an_expired_withdrawal_takes_nothing_and_the_minute_expires_it(self, stack):
        await funded(stack)
        withdrawal = await started(stack)
        stack.clock.advance(10 * 60)
        assert await code_of(approved(stack, withdrawal)) == "WITHDRAWAL_EXPIRED"
        await stack.app.background.minute()
        assert await state_of(stack, withdrawal) == "expired" and await kinds(stack) == ["fund"]

    async def test_pressing_withdraw_again_finds_the_first_and_pays_once(self, stack):
        await funded(stack)
        withdrawal = await started(stack)
        first, again = await approved(stack, withdrawal), await approved(stack, withdrawal)
        assert first.state == again.state == "succeeded"
        assert await kinds(stack) == ["fund", "withdraw"] and await stack.count("sim_transfers") == 1


class TestTheRulesAtTheMoment:
    async def test_money_spent_after_starting_is_not_withdrawn(self, stack):
        await funded(stack, 3_000_000)
        withdrawal = await started(stack, 2_000_000)
        await withdrawals(stack).journal.debit(ALICE, "spend", 1_500_000, "qt-1")
        assert await code_of(approved(stack, withdrawal)) == "WALLET_SHORT"
        assert await balance(stack) == 1_500_000 and await state_of(stack, withdrawal) == "open"

    async def test_a_wallet_frozen_after_starting_pays_nothing(self, stack):
        await funded(stack)
        withdrawal = await started(stack)
        await withdrawals(stack).journal.set_frozen(ALICE, True)
        assert await code_of(approved(stack, withdrawal)) == "WALLET_FROZEN"
        assert await kinds(stack) == ["fund"]

    async def test_the_daily_cap_counts_what_left_today(self, stack):
        await funded(stack, 20_000_000)
        for _ in range(2):
            await approved(stack, await started(stack, 5_000_000))
        assert await code_of(started(stack, 100_000)) == "WITHDRAWAL_DAILY"

    async def test_the_daily_cap_is_held_when_the_money_is_taken(self, stack):
        await funded(stack, 20_000_000)
        waiting = [await started(stack, 5_000_000) for _ in range(3)]
        outcomes = [await code_of(approved(stack, w)) for w in waiting]
        assert outcomes == ["none", "none", "WITHDRAWAL_DAILY"]
        assert await balance(stack) == 10_000_000

    async def test_money_given_back_does_not_count_today_and_tomorrow_starts_again(self, stack):
        await funded(stack, 20_000_000)
        first = await approved(stack, await started(stack, 5_000_000))
        await approved(stack, await started(stack, 5_000_000))
        await set_transfer(stack, first, "reversed")
        assert (await withdrawals(stack).outcomes.recheck(first.id)).state == "reversed"
        await approved(stack, await started(stack, 5_000_000))
        assert await code_of(started(stack, 100_000)) == "WITHDRAWAL_DAILY"
        stack.clock.advance(24 * 60 * 60)
        assert (await approved(stack, await started(stack, 5_000_000))).state == "succeeded"

    async def test_the_per_withdrawal_cap_is_held_when_the_money_is_taken(self, stack):
        await funded(stack, 20_000_000)
        withdrawal = await started(stack, 5_000_000)
        object.__setattr__(withdrawals(stack).journal.settings, "withdrawal_kobo", 4_000_000)
        assert await code_of(approved(stack, withdrawal)) == "WITHDRAWAL_CAP"
        assert await kinds(stack) == ["fund"]


class TestTheDisputeBlock:
    async def test_nobody_is_blocked_until_a_block_is_written(self, stack):
        await funded(stack)
        assert await withdrawals_blocked(stack.db, ALICE) is False

    async def test_a_block_refuses_a_new_withdrawal(self, stack):
        await funded(stack)
        await block(stack)
        assert await withdrawals_blocked(stack.db, ALICE) is True
        assert await code_of(started(stack)) == "WITHDRAWALS_BLOCKED"

    async def test_a_block_written_after_starting_stops_the_money_leaving(self, stack):
        await funded(stack)
        withdrawal = await started(stack)
        await block(stack)
        assert await code_of(approved(stack, withdrawal)) == "WITHDRAWALS_BLOCKED"
        assert await kinds(stack) == ["fund"] and await stack.count("sim_transfers") == 0

    async def test_a_lifted_block_and_another_owners_block_stop_nothing(self, stack):
        await funded(stack)
        await funded(stack, owner=BOB)
        await block(stack, ALICE, lifted_at=stack.clock.now())
        await block(stack, BOB)
        assert (await approved(stack, await started(stack))).state == "succeeded"
