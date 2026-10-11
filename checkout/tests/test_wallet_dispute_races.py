# SPDX-License-Identifier: AGPL-3.0-or-later
"""A dispute arriving while the wallet spends or withdraws (SqliteDb interleaves callers between statements,
as D1 does): however they interleave, the wallet never goes below ₦0, the hold and the other debit never take
the same money, and a withdrawal the dispute's block reaches first takes nothing."""

import asyncio

import pytest

from checkout.errors import DomainError
from tests.dispute_support import dispute_event, disputed, paid, record
from tests.support import ALICE, make_stack
from tests.topup_support import SECRET, balance, deliver, topups
from tests.withdrawal_support import approved, started

FUNDED = 3_000_000


@pytest.fixture
def stack():
    return make_stack(approval_secret=SECRET)


async def taken(stack, kind: str) -> int:
    rows = await stack.rows(
        "SELECT COALESCE(SUM(amount_kobo), 0) AS s FROM wallet_entry WHERE kind = ?", kind
    )
    return rows[0]["s"]


async def withdraw_or_refusal(stack, withdrawal) -> str:
    try:
        return (await approved(stack, withdrawal)).state
    except DomainError as error:
        return error.code


async def after(turns: int, work):
    """`work`, started once the event loop has run the others `turns` times."""
    for _ in range(turns):
        await asyncio.sleep(0)
    return await work


LEADS = [-4, -2, -1, 0, 1, 2, 3, 4, 6, 8]
"""How many turns the dispute starts ahead of the other side (behind, when negative): each lands its
statements at another point among the other's."""


def turns(lead: int) -> tuple[int, int]:
    return max(-lead, 0), max(lead, 0)


@pytest.mark.parametrize("lead", LEADS)
@pytest.mark.parametrize("spends", [1, 3, 6])
async def test_a_dispute_racing_spends_never_takes_the_wallet_below_zero(stack, spends, lead):
    topup = await paid(stack, FUNDED)
    journal = topups(stack).journal
    first, then = turns(lead)
    debits = [after(then + 2 * n, journal.debit(ALICE, "spend", 1_000_000, f"qt-{n}")) for n in range(spends)]
    landed = await asyncio.gather(after(first, deliver(stack, disputed(topup))), *debits)
    spent = sum(1_000_000 for entry in landed[1:] if entry is not None)
    held = (await record(stack)).held_kobo
    assert await balance(stack) == FUNDED - spent - held >= 0
    assert spent == await taken(stack, "spend") and held == await taken(stack, "dispute")
    assert held + spent <= FUNDED
    assert await journal.is_frozen(ALICE) == (held < FUNDED)


@pytest.mark.parametrize("lead", LEADS)
async def test_a_dispute_racing_a_withdrawal_lets_only_one_take_the_money(stack, lead):
    topup = await paid(stack, FUNDED)
    withdrawal = await started(stack, 2_000_000)
    first, then = turns(lead)
    outcome, _ = await asyncio.gather(
        after(then, withdraw_or_refusal(stack, withdrawal)), after(first, dispute_event(stack, topup))
    )
    held = (await record(stack)).held_kobo
    withdrawn = await taken(stack, "withdraw")
    assert held + withdrawn <= FUNDED and await balance(stack) == FUNDED - held - withdrawn >= 0
    assert (outcome == "succeeded") == (withdrawn == 2_000_000)
    assert outcome in {"succeeded", "WITHDRAWALS_BLOCKED", "WALLET_SHORT"}


async def test_a_withdrawal_pressed_after_the_dispute_opens_takes_nothing(stack):
    topup = await paid(stack, FUNDED)
    await topups(stack).journal.credit(ALICE, "fund", 1_000_000, "top-up-other")
    withdrawal = await started(stack, 500_000)
    await dispute_event(stack, topup)
    assert await withdraw_or_refusal(stack, withdrawal) == "WITHDRAWALS_BLOCKED"
    assert await taken(stack, "withdraw") == 0 and await balance(stack) == 1_000_000
    with pytest.raises(DomainError) as refused:
        await started(stack, 500_000)
    assert refused.value.code == "WITHDRAWALS_BLOCKED"


async def test_after_the_dispute_ends_the_owner_withdraws_again(stack):
    topup = await paid(stack, FUNDED)
    await dispute_event(stack, topup)
    await dispute_event(stack, topup, "won", event="dispute.updated")
    withdrawal = await started(stack, 500_000)
    assert await withdraw_or_refusal(stack, withdrawal) == "succeeded"
    assert await balance(stack) == FUNDED - 500_000
