# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wallet journal's invariants (wallet/journal.py, migrations/0011_wallet.sql): the balance is the sum of
the entries and never goes below zero, a ref moves money once, a frozen wallet pays nothing, and the cap
bounds what funding may bring in."""

import sqlite3

import pytest

from checkout.errors import DomainError
from tests.support import ALICE, BOB
from tests.wallet_support import CAP, new_journal


@pytest.fixture
def journal():
    return new_journal()


async def test_the_balance_is_the_signed_sum_of_the_entries(journal):
    await journal.credit(ALICE, "fund", 500_000, "top-up-1")
    await journal.debit(ALICE, "spend", 120_000, "qt-1")
    await journal.credit(ALICE, "release", 120_000, "qt-1")
    await journal.debit(ALICE, "spend", 80_000, "qt-2")
    assert await journal.balance(ALICE) == 420_000
    assert await journal.balance(BOB) == 0


async def test_history_is_newest_first_and_limited(journal):
    await journal.credit(ALICE, "fund", 500_000, "top-up-1")
    await journal.debit(ALICE, "spend", 100_000, "qt-1")
    await journal.credit(ALICE, "refund", 100_000, "qt-1")
    history = await journal.history(ALICE, 2)
    assert [(e.kind, e.signed_kobo) for e in history] == [("refund", 100_000), ("spend", -100_000)]
    assert await journal.history(BOB) == []


async def test_a_debit_the_balance_does_not_cover_is_refused_and_writes_nothing(journal):
    await journal.credit(ALICE, "fund", 100_000, "top-up-1")
    assert await journal.debit(ALICE, "spend", 100_001, "qt-1") is None
    assert await journal.balance(ALICE) == 100_000
    assert await journal.debit(ALICE, "spend", 100_000, "qt-2") is not None
    assert await journal.balance(ALICE) == 0
    assert await journal.debit(ALICE, "spend", 1, "qt-3") is None
    assert len(await journal.history(ALICE)) == 2


async def test_a_debit_from_a_wallet_that_does_not_exist_is_refused(journal):
    assert await journal.debit(BOB, "spend", 1, "qt-1") is None
    assert await journal.history(BOB) == []


async def test_a_repeated_credit_ref_is_answered_by_the_first_entry(journal):
    first = await journal.credit(ALICE, "fund", 300_000, "top-up-1")
    again = await journal.credit(ALICE, "fund", 300_000, "top-up-1")
    assert first == again
    assert await journal.balance(ALICE) == 300_000


async def test_a_repeated_debit_ref_is_answered_by_the_first_entry_even_once_the_money_is_gone(journal):
    await journal.credit(ALICE, "fund", 300_000, "top-up-1")
    first = await journal.debit(ALICE, "spend", 300_000, "qt-1")
    again = await journal.debit(ALICE, "spend", 300_000, "qt-1")
    assert first is not None and first == again
    assert await journal.balance(ALICE) == 0


async def test_a_ref_reused_for_another_amount_is_refused(journal):
    await journal.credit(ALICE, "fund", 300_000, "top-up-1")
    with pytest.raises(DomainError) as refused:
        await journal.credit(ALICE, "fund", 400_000, "top-up-1")
    assert refused.value.code == "WALLET_REF_CONFLICT"
    assert await journal.balance(ALICE) == 300_000


async def test_the_same_ref_in_another_owners_wallet_is_their_own(journal):
    await journal.credit(ALICE, "fund", 300_000, "top-up-1")
    await journal.credit(BOB, "fund", 200_000, "top-up-1")
    assert (await journal.balance(ALICE), await journal.balance(BOB)) == (300_000, 200_000)


async def test_a_frozen_wallet_refuses_debits_and_still_takes_money_back(journal):
    await journal.credit(ALICE, "fund", 300_000, "top-up-1")
    assert await journal.set_frozen(ALICE, True)
    assert await journal.debit(ALICE, "spend", 1, "qt-1") is None
    assert await journal.debit(ALICE, "withdraw", 1, "wd-1") is None
    assert await journal.credit(ALICE, "refund", 50_000, "qt-0") is not None
    assert await journal.set_frozen(ALICE, False)
    assert await journal.debit(ALICE, "spend", 1, "qt-1") is not None


async def test_freezing_a_wallet_that_does_not_exist_says_so(journal):
    assert not await journal.set_frozen(BOB, True)


async def test_the_cap_refuses_funding_above_it_and_takes_funding_up_to_it(journal):
    assert await journal.credit(ALICE, "fund", CAP - 1, "top-up-1") is not None
    assert await journal.credit(ALICE, "fund", 2, "top-up-2") is None
    assert await journal.credit(ALICE, "fund", 1, "top-up-3") is not None
    assert await journal.balance(ALICE) == CAP


async def test_the_cap_never_holds_back_money_the_wallet_already_had(journal):
    await journal.credit(ALICE, "fund", CAP, "top-up-1")
    await journal.debit(ALICE, "spend", 500_000, "qt-1")
    await journal.credit(ALICE, "fund", 500_000, "top-up-2")
    assert await journal.credit(ALICE, "refund", 500_000, "qt-1") is not None
    assert await journal.balance(ALICE) == CAP + 500_000


@pytest.mark.parametrize("amount", [0, -5, 1.5, True])
async def test_an_amount_is_a_positive_whole_number_of_kobo(journal, amount):
    with pytest.raises(DomainError):
        await journal.credit(ALICE, "fund", amount, "top-up-1")


@pytest.mark.parametrize(("move", "kind"), [("credit", "spend"), ("credit", "withdraw"), ("debit", "fund")])
async def test_a_kind_moves_money_one_way(journal, move, kind):
    with pytest.raises(ValueError, match="is not a"):
        await getattr(journal, move)(ALICE, kind, 1, "ref-1")


class TestTheSchemaRefusesBadRows:
    @staticmethod
    async def _insert(journal, kind: str, sign: int, amount, owner: str = ALICE, ref: str = "r-1") -> None:
        await journal.open(ALICE)
        await journal._db.execute(
            "INSERT INTO wallet_entry (id, owner, kind, sign, amount_kobo, ref, created_at) "
            "VALUES ('we-x', ?, ?, ?, ?, ?, 0)",
            owner,
            kind,
            sign,
            amount,
            ref,
        )

    @pytest.mark.parametrize(
        ("kind", "sign", "amount", "ref"),
        [
            ("spend", 1, 100, "r-1"),
            ("fund", -1, 100, "r-1"),
            ("refund", -1, 100, "r-1"),
            ("adjust", 0, 100, "r-1"),
            ("fund", 1, 0, "r-1"),
            ("fund", 1, -100, "r-1"),
            ("fund", 1, 1.5, "r-1"),
            ("bonus", 1, 100, "r-1"),
            ("fund", 1, 100, ""),
        ],
    )
    async def test_rows_that_break_a_rule(self, journal, kind, sign, amount, ref):
        with pytest.raises(sqlite3.IntegrityError):
            await self._insert(journal, kind, sign, amount, ref=ref)

    async def test_an_entry_for_a_wallet_that_does_not_exist(self, journal):
        with pytest.raises(sqlite3.IntegrityError):
            await self._insert(journal, "fund", 1, 100, owner=BOB)

    @pytest.mark.parametrize("owner", ["p:agent-1", "A1" * 16, "a1" * 15])
    async def test_a_wallet_for_anything_but_an_owner_key(self, journal, owner):
        with pytest.raises(sqlite3.IntegrityError):
            await journal.open(owner)

    async def test_an_entry_cannot_be_changed_or_removed(self, journal):
        await journal.credit(ALICE, "fund", 100, "top-up-1")
        with pytest.raises(sqlite3.IntegrityError, match="cannot be changed"):
            await journal._db.execute("UPDATE wallet_entry SET amount_kobo = 1000000")
        with pytest.raises(sqlite3.IntegrityError, match="cannot be removed"):
            await journal._db.execute("DELETE FROM wallet_entry")
        assert await journal.balance(ALICE) == 100
