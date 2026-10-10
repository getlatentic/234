# SPDX-License-Identifier: AGPL-3.0-or-later
"""Withdrawals pressed at the same moment (SqliteDb interleaves callers between statements, as D1 does):
however they interleave, they never take a wallet below zero, never pass the daily cap, and one withdrawal
pressed many times takes its money and sends its transfer once."""

import asyncio

from checkout.errors import DomainError
from tests.support import ALICE
from tests.withdrawal_support import approved, balance, funded, kinds, started


async def press_all(stack, waiting) -> list[str]:
    async def press(withdrawal):
        try:
            return (await approved(stack, withdrawal)).state
        except DomainError as error:
            return error.code

    return await asyncio.gather(*[press(w) for w in waiting])


async def test_racing_withdrawals_never_take_more_than_the_wallet_holds(stack):
    await funded(stack, 7_000_000)
    waiting = [await started(stack, 2_000_000) for _ in range(6)]
    outcomes = await press_all(stack, waiting)
    assert sorted(outcomes) == ["WALLET_SHORT"] * 3 + ["succeeded"] * 3
    assert await balance(stack) == 1_000_000
    assert await stack.count("sim_transfers") == 3


async def test_racing_withdrawals_never_pass_the_daily_cap(stack):
    await funded(stack, 20_000_000)
    waiting = [await started(stack, 3_000_000) for _ in range(6)]
    outcomes = await press_all(stack, waiting)
    assert outcomes.count("succeeded") == 3
    assert await balance(stack) == 11_000_000
    taken = await stack.rows("SELECT SUM(amount_kobo) AS s FROM wallet_entry WHERE kind = 'withdraw'")
    assert taken[0]["s"] == 9_000_000


async def test_one_withdrawal_pressed_many_times_at_once_pays_once(stack):
    await funded(stack)
    withdrawal = await started(stack)
    outcomes = await press_all(stack, [withdrawal] * 8)
    assert set(outcomes) <= {"succeeded", "sent"}
    assert await kinds(stack, ALICE) == ["fund", "withdraw"]
    assert await stack.count("sim_transfers") == 1


async def test_a_withdrawal_racing_a_spend_leaves_no_negative_balance(stack):
    await funded(stack, 2_000_000)
    withdrawal = await started(stack, 2_000_000)
    journal = stack.app.withdrawals.journal
    spent, pressed = await asyncio.gather(
        journal.debit(ALICE, "spend", 1_500_000, "qt-1"), press_all(stack, [withdrawal])
    )
    assert (spent is None) == (pressed == ["succeeded"])
    assert await balance(stack) >= 0
