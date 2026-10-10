# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the wallet journal guarantees when callers race (SqliteDb interleaves them between statements, as
D1 does): spends that cannot all fit never all land, one ref lands once, and funding never passes the cap.
The control spends by reading the balance and then writing, and overspends, so the tests above it can fail."""

import asyncio

from checkout.wallet.journal import BALANCE_SQL, Journal
from tests.support import ALICE, BOB
from tests.wallet_support import CAP, new_journal


async def _spend_racing(journal: Journal, owner: str, count: int, amount: int) -> list:
    return await asyncio.gather(
        *[journal.debit(owner, "spend", amount, f"qt-{owner[:2]}-{i}") for i in range(count)]
    )


async def test_twenty_racing_spends_of_one_wallet_never_overspend_it():
    journal = new_journal()
    await journal.credit(ALICE, "fund", 1_000_000, "top-up-1")
    landed = await _spend_racing(journal, ALICE, 20, 300_000)
    assert sum(entry is not None for entry in landed) == 3
    assert await journal.balance(ALICE) == 100_000


async def test_racing_spends_of_two_wallets_each_stop_at_their_own_balance():
    journal = new_journal()
    await journal.credit(ALICE, "fund", 1_000_000, "top-up-1")
    await journal.credit(BOB, "fund", 500_000, "top-up-1")
    alices, bobs = await asyncio.gather(
        _spend_racing(journal, ALICE, 10, 250_000), _spend_racing(journal, BOB, 10, 250_000)
    )
    assert (sum(e is not None for e in alices), sum(e is not None for e in bobs)) == (4, 2)
    assert (await journal.balance(ALICE), await journal.balance(BOB)) == (0, 0)


async def test_the_same_webhook_delivered_many_times_at_once_credits_once():
    journal = new_journal()
    answers = await asyncio.gather(*[journal.credit(ALICE, "fund", 400_000, "top-up-7") for _ in range(10)])
    assert len({a.id for a in answers}) == 1
    assert await journal.balance(ALICE) == 400_000
    assert len(await journal.history(ALICE)) == 1


async def test_the_same_spend_retried_many_times_at_once_debits_once():
    journal = new_journal()
    await journal.credit(ALICE, "fund", 1_000_000, "top-up-1")
    answers = await asyncio.gather(*[journal.debit(ALICE, "spend", 300_000, "qt-1") for _ in range(10)])
    assert len({a.id for a in answers}) == 1
    assert await journal.balance(ALICE) == 700_000


async def test_racing_top_ups_never_take_a_wallet_past_the_cap():
    journal = new_journal()
    await asyncio.gather(*[journal.credit(ALICE, "fund", CAP // 4, f"top-up-{i}") for i in range(10)])
    assert await journal.balance(ALICE) == CAP


async def _naive_spend(journal: Journal, owner: str, amount: int, ref: str) -> bool:
    db = journal._db
    row = await db.row(f"SELECT {BALANCE_SQL} AS balance", owner)
    if row["balance"] < amount:
        return False
    await db.execute(
        "INSERT INTO wallet_entry (id, owner, kind, sign, amount_kobo, ref, created_at) "
        "VALUES (?, ?, 'spend', -1, ?, ?, 0)",
        f"we-{ref}",
        owner,
        amount,
        ref,
    )
    return True


async def test_the_read_then_write_control_does_overspend_so_the_tests_above_can_fail():
    journal = new_journal()
    await journal.credit(ALICE, "fund", 1_000_000, "top-up-1")
    await asyncio.gather(*[_naive_spend(journal, ALICE, 300_000, f"qt-{i}") for i in range(20)])
    assert await journal.balance(ALICE) < 0
