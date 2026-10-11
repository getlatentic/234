# SPDX-License-Identifier: AGPL-3.0-or-later
"""A chargeback on a top-up (wallet/disputes.py): the disputed amount is held once, whatever the events'
number and order; withdrawals are blocked while it is open and spending is not; a wallet the hold cannot cover
holds what it has and is frozen, never going below ₦0; won and closed write the hold back, lost and prevented
keep it and write off the shortfall; and every ending lifts the dispute's own block and freeze alone."""

import pytest

from checkout.errors import DomainError
from checkout.wallet.view import WalletView
from checkout.wallet.withdrawal_block import withdrawals_blocked
from tests.dispute_support import (
    DISPUTE,
    blocks,
    dispute_event,
    disputed,
    freezes,
    kinds,
    paid,
    record,
)
from tests.support import ALICE, make_stack
from tests.topup_support import SECRET, audited, balance, charge_of, deliver, started, succeeded, topups


@pytest.fixture
def stack():
    return make_stack(approval_secret=SECRET)


def journal(stack):
    return topups(stack).journal


async def spend(stack, amount: int, ref: str = "qt-1"):
    return await journal(stack).debit(ALICE, "spend", amount, ref)


async def frozen(stack) -> bool:
    return await journal(stack).is_frozen(ALICE)


class TestTheCharge:
    async def test_a_credited_collection_keeps_its_charge_on_the_top_up(self, stack):
        topup = await paid(stack)
        assert topup.charge_id == charge_of(topup) == await charge_row(stack, topup.id)
        assert [line for line in stack.audit_lines if "wallet.dispute" in line] == []

    async def test_a_collection_that_credits_nothing_keeps_no_charge(self, stack):
        topup = await started(stack)
        assert (await deliver(stack, succeeded(topup, amount="1.00"))).status == 200
        assert await charge_row(stack, topup.id) is None

    async def test_a_repeated_delivery_records_a_charge_the_first_did_not_carry(self, stack):
        topup = await started(stack)
        assert (await deliver(stack, succeeded(topup, charge_id=None))).status == 200
        assert await charge_row(stack, topup.id) is None
        assert (await deliver(stack, succeeded(topup))).status == 200
        assert await charge_row(stack, topup.id) == charge_of(topup) and await balance(stack) == 500_000

    async def test_a_charge_another_top_up_holds_is_not_recorded_and_still_credits(self, stack):
        first = await paid(stack)
        second = await started(stack)
        assert (await deliver(stack, succeeded(second, charge_id=charge_of(first)))).status == 200
        assert await charge_row(stack, second.id) is None and await balance(stack) == 1_000_000


async def charge_row(stack, topup_id: str) -> str | None:
    [row] = await stack.rows("SELECT charge_id FROM wallet_topup WHERE id = ?", topup_id)
    return row["charge_id"]


class TestOpening:
    async def test_a_dispute_holds_the_amount_and_blocks_withdrawals_but_not_spending(self, stack):
        topup = await paid(stack)
        await dispute_event(stack, topup)
        assert await kinds(stack) == [("fund", 500_000), ("dispute", 500_000)]
        assert await balance(stack) == 0 and not await frozen(stack)
        assert await withdrawals_blocked(stack.db, ALICE)
        assert await freezes(stack) == []
        found = await record(stack)
        assert (found.state, found.held_kobo, found.topup_id, found.owner) == (
            "open",
            500_000,
            topup.id,
            ALICE,
        )
        [opened] = audited(stack, "wallet.dispute.opened")
        assert (opened["dispute"], opened["held_kobo"]) == (DISPUTE, 500_000)
        assert audited(stack, "wallet.dispute.short") == []

    async def test_spending_from_an_open_dispute_wallet_still_works(self, stack):
        await paid(stack, 300_000)
        topup = await paid(stack, 200_000)
        await dispute_event(stack, topup)
        assert await balance(stack) == 300_000
        assert await spend(stack, 300_000) is not None and await balance(stack) == 0

    async def test_a_dispute_for_part_of_a_charge_holds_that_part(self, stack):
        topup = await paid(stack)
        await dispute_event(stack, topup, amount="1200.50")
        assert await kinds(stack) == [("fund", 500_000), ("dispute", 120_050)]
        assert (await record(stack)).amount_kobo == 120_050

    async def test_the_same_event_delivered_again_holds_once(self, stack):
        topup = await paid(stack, 300_000)
        await paid(stack, 400_000)
        for _ in range(3):
            await dispute_event(stack, topup)
        assert await kinds(stack) == [("fund", 300_000), ("fund", 400_000), ("dispute", 300_000)]
        assert len(await blocks(stack)) == 1 and len(audited(stack, "wallet.dispute.opened")) == 1

    async def test_an_update_before_its_created_opens_it_once(self, stack):
        topup = await paid(stack)
        await dispute_event(stack, topup, "under_review", event="dispute.updated")
        await dispute_event(stack, topup)
        assert await kinds(stack) == [("fund", 500_000), ("dispute", 500_000)]
        assert (await record(stack)).state == "open"


class TestShort:
    async def test_a_wallet_short_of_the_amount_holds_what_it_has_and_is_frozen(self, stack):
        topup = await paid(stack)
        await spend(stack, 350_000)
        await dispute_event(stack, topup)
        assert await kinds(stack) == [("fund", 500_000), ("spend", 350_000), ("dispute", 150_000)]
        assert await balance(stack) == 0 and await frozen(stack)
        [freeze] = await freezes(stack)
        assert (freeze["reason"], freeze["ref"], freeze["lifted_at"]) == ("dispute", DISPUTE, None)
        [short] = audited(stack, "wallet.dispute.short")
        assert (short["held_kobo"], short["amount_kobo"]) == (150_000, 500_000)

    async def test_a_frozen_wallet_takes_no_top_up_and_pays_nothing(self, stack):
        topup = await paid(stack)
        await spend(stack, 500_000)
        await dispute_event(stack, topup)
        await journal(stack).credit(ALICE, "release", 500_000, "qt-1")
        assert await balance(stack) == 500_000
        assert await spend(stack, 100, "qt-2") is None
        with pytest.raises(DomainError) as refused:
            await topups(stack).start(ALICE, 100_000)
        assert refused.value.code == "WALLET_FROZEN"

    async def test_an_empty_wallet_holds_nothing_and_is_frozen(self, stack):
        topup = await paid(stack)
        await spend(stack, 500_000)
        await dispute_event(stack, topup)
        assert [kind for kind, _ in await kinds(stack)] == ["fund", "spend"]
        assert (await record(stack)).held_kobo == 0 and await frozen(stack)

    async def test_money_arriving_while_frozen_is_not_held_by_a_repeated_event(self, stack):
        topup = await paid(stack)
        await spend(stack, 500_000)
        await dispute_event(stack, topup)
        await journal(stack).credit(ALICE, "release", 500_000, "qt-1")
        await dispute_event(stack, topup, "under_review", event="dispute.updated")
        assert (await record(stack)).held_kobo == 0 and await balance(stack) == 500_000


class TestDeciding:
    @pytest.mark.parametrize("status", ["won", "closed"])
    async def test_kept_by_234_the_hold_is_written_back_and_the_block_lifted(self, stack, status):
        topup = await paid(stack)
        await dispute_event(stack, topup)
        await dispute_event(stack, topup, status, event="dispute.updated")
        assert await kinds(stack) == [("fund", 500_000), ("dispute", 500_000), ("dispute_back", 500_000)]
        assert await balance(stack) == 500_000 and not await withdrawals_blocked(stack.db, ALICE)
        found = await record(stack)
        assert (found.state, found.written_off_kobo) == (status, 0)
        [decided] = audited(stack, "wallet.dispute.decided")
        assert (decided["state"], decided["written_off_kobo"]) == (status, 0)

    @pytest.mark.parametrize("status", ["lost", "prevented"])
    async def test_lost_by_234_the_hold_stays_and_the_block_is_lifted(self, stack, status):
        topup = await paid(stack)
        await dispute_event(stack, topup)
        await dispute_event(stack, topup, status, event="dispute.updated")
        assert await kinds(stack) == [("fund", 500_000), ("dispute", 500_000)]
        assert await balance(stack) == 0 and not await withdrawals_blocked(stack.db, ALICE)
        found = await record(stack)
        assert (found.state, found.written_off_kobo) == (status, 0)

    @pytest.mark.parametrize(("status", "back", "written_off"), [("won", 150_000, 0), ("lost", 0, 350_000)])
    async def test_a_short_dispute_ends_with_the_freeze_lifted(self, stack, status, back, written_off):
        topup = await paid(stack)
        await spend(stack, 350_000)
        await dispute_event(stack, topup)
        await dispute_event(stack, topup, status, event="dispute.updated")
        assert await balance(stack) == back and not await frozen(stack)
        assert (await record(stack)).written_off_kobo == written_off
        [freeze] = await freezes(stack)
        assert freeze["lifted_at"] == stack.clock.now()

    async def test_an_empty_wallet_that_loses_writes_off_the_whole_amount(self, stack):
        topup = await paid(stack)
        await spend(stack, 500_000)
        await dispute_event(stack, topup)
        await dispute_event(stack, topup, "lost", event="dispute.updated")
        assert (await record(stack)).written_off_kobo == 500_000
        assert await balance(stack) == 0 and not await frozen(stack)
        written_off = await stack.rows(
            "SELECT SUM(written_off_kobo) AS s FROM wallet_dispute WHERE state = 'lost'"
        )
        assert written_off[0]["s"] == 500_000

    async def test_a_decision_delivered_again_writes_back_once(self, stack):
        topup = await paid(stack)
        await dispute_event(stack, topup)
        for _ in range(3):
            await dispute_event(stack, topup, "won", event="dispute.updated")
        assert [kind for kind, _ in await kinds(stack)] == ["fund", "dispute", "dispute_back"]
        assert len(audited(stack, "wallet.dispute.decided")) == 1

    async def test_a_decision_before_its_created_opens_and_decides_it(self, stack):
        topup = await paid(stack)
        await dispute_event(stack, topup, "won", event="dispute.updated")
        await dispute_event(stack, topup)
        assert [kind for kind, _ in await kinds(stack)] == ["fund", "dispute", "dispute_back"]
        assert (await record(stack)).state == "won" and await balance(stack) == 500_000
        assert not await withdrawals_blocked(stack.db, ALICE)

    async def test_a_late_created_after_the_decision_does_nothing(self, stack):
        topup = await paid(stack)
        await dispute_event(stack, topup)
        await dispute_event(stack, topup, "lost", event="dispute.updated")
        await paid(stack, 200_000)
        await dispute_event(stack, topup)
        await dispute_event(stack, topup, "won", event="dispute.updated")
        assert (await record(stack)).state == "lost" and await balance(stack) == 200_000
        assert not await withdrawals_blocked(stack.db, ALICE) and not await frozen(stack)

    async def test_a_decided_dispute_opens_nothing_again(self, stack):
        topup = await paid(stack)
        await stack.db.execute(
            "INSERT INTO wallet_dispute (id, owner, topup_id, charge_id, amount_kobo, state, "
            "written_off_kobo, created_at, decided_at) VALUES (?, ?, ?, ?, ?, 'lost', ?, ?, ?)",
            DISPUTE, ALICE, topup.id, topup.charge_id, 500_000, 500_000, stack.clock.now(), stack.clock.now(),
        )  # fmt: skip
        await dispute_event(stack, topup)
        assert await kinds(stack) == [("fund", 500_000)] and await blocks(stack) == []
        assert await freezes(stack) == [] and audited(stack, "wallet.dispute.opened") == []

    async def test_a_wallet_frozen_by_operations_stays_frozen_after_a_dispute_ends(self, stack):
        topup = await paid(stack)
        await spend(stack, 500_000)
        await journal(stack).set_frozen(ALICE, True)
        await dispute_event(stack, topup)
        await dispute_event(stack, topup, "won", event="dispute.updated")
        assert await frozen(stack)

    async def test_ending_one_short_dispute_leaves_another_ones_freeze(self, stack):
        first, second = await paid(stack, 300_000), await paid(stack, 200_000)
        await spend(stack, 500_000)
        await dispute_event(stack, first, dispute_id="dsp_first")
        await dispute_event(stack, second, dispute_id="dsp_second")
        await dispute_event(stack, first, "won", event="dispute.updated", dispute_id="dsp_first")
        assert await frozen(stack) and await withdrawals_blocked(stack.db, ALICE)
        await dispute_event(stack, second, "lost", event="dispute.updated", dispute_id="dsp_second")
        assert not await frozen(stack) and not await withdrawals_blocked(stack.db, ALICE)


class TestRefused:
    @pytest.mark.parametrize(
        ("change", "reason"),
        [
            ({"currency": "USD"}, "currency"),
            ({"amount": "5000.01"}, "amount"),
            ({"amount": "0.00"}, "amount"),
            ({"amount": 500000}, "shape"),
            ({"dispute_id": None}, "shape"),
            ({"charge_id": None}, "shape"),
        ],
    )
    async def test_a_dispute_234_cannot_place_holds_nothing_and_is_audited(self, stack, change, reason):
        topup = await paid(stack)
        answer = await deliver(stack, disputed(topup, **change))
        assert answer.status == 200
        assert await kinds(stack) == [("fund", 500_000)] and await blocks(stack) == []
        assert await stack.count("wallet_dispute") == 0
        assert [line["reason"] for line in audited(stack, "wallet.dispute.refused")] == [reason]

    async def test_a_dispute_naming_no_credited_charge_is_asked_for_again(self, stack):
        answer = await deliver(stack, disputed(await paid(stack), charge_id="ch_not_credited_yet"))
        assert answer.status == 503
        assert await stack.count("wallet_dispute") == 0
        assert [line["reason"] for line in audited(stack, "wallet.dispute.refused")] == ["unknown"]

    async def test_a_dispute_on_a_top_up_not_yet_paid_holds_once_its_collection_is_credited(self, stack):
        await paid(stack)
        topup = await started(stack)
        assert (await deliver(stack, disputed(topup))).status == 503
        assert await stack.count("wallet_dispute") == 0
        assert (await deliver(stack, succeeded(topup))).status == 200
        assert (await deliver(stack, disputed(topup))).status == 200
        assert await stack.count("wallet_dispute") == 1


class TestShown:
    async def test_the_card_says_the_hold_and_that_withdrawals_are_paused(self, stack):
        topup = await paid(stack)
        await dispute_event(stack, topup)
        view = await WalletView(journal(stack), stack.db).of(ALICE)
        assert view["withdrawalsBlocked"] is True and view["frozen"] is False
        newest = view["entries"][0]
        assert (newest["label"], newest["amount"]) == ("Held for a dispute", "-₦5,000")
        await dispute_event(stack, topup, "won", event="dispute.updated")
        view = await WalletView(journal(stack), stack.db).of(ALICE)
        assert view["entries"][0]["label"] == "Returned after a dispute"
        assert view["withdrawalsBlocked"] is False
