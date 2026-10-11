# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wallet's reconciliation (wallet/reconciliation.py): what 234 owes every wallet against what it holds at
Bachs, Paystack and VTpass; a provider that cannot be read is unknown, never zero; a short run pauses new
top-ups until a complete run is not short; a run once an hour from the cron and on an operator's request; and
each run kept as it was."""

import json
import sqlite3

import pytest

from checkout.audit import Audit
from checkout.bachs.api import BachsError
from checkout.errors import DomainError
from checkout.http import handle
from checkout.paystack.api import PaystackError
from checkout.vtpass.api import AccessCheck
from checkout.wallet.reconciliation import EVERY_MS, Reconciliation
from checkout.wallet.treasury import Treasury
from tests.dispute_support import dispute_event, paid
from tests.support import ALICE, BOB, make_stack
from tests.topup_support import audited, started

TOKEN = "ops-token-not-real"


class Balance:
    """A provider whose balance a test sets; an exception for one that cannot be read."""

    def __init__(self, kobo: int | Exception) -> None:
        self.kobo = kobo

    async def ngn_balance(self) -> int:
        if isinstance(self.kobo, Exception):
            raise self.kobo
        return self.kobo

    async def check_access(self) -> AccessCheck:
        if isinstance(self.kobo, Exception):
            return AccessCheck(False, reason=str(self.kobo))
        return AccessCheck(True, balance_kobo=self.kobo)


@pytest.fixture
def stack():
    return make_stack(ops_token=TOKEN)


def reconciliation(stack, bachs=0, paystack=0, vtpass=0) -> Reconciliation:
    audit = Audit([stack.audit_lines.append], stack.clock)
    treasury = Treasury(Balance(bachs), Balance(paystack), Balance(vtpass), audit)
    return Reconciliation(stack.db, stack.clock, treasury, audit)


async def owe(stack, owner: str = ALICE, amount: int = 500_000) -> None:
    journal = stack.app.withdrawals.journal
    await journal.credit(owner, "fund", amount, f"top-up-{owner}-{amount}")


class TestTheBooks:
    async def test_what_234_owes_is_every_wallet_together(self, stack):
        await owe(stack, ALICE, 500_000)
        await owe(stack, BOB, 250_000)
        await stack.app.withdrawals.journal.debit(BOB, "spend", 50_000, "q-1")
        report = await reconciliation(stack, 700_000).run()
        assert report.books.owed_kobo == 700_000 and report.gap_kobo == 0 and not report.short

    async def test_disputes_are_234s_cost_never_a_wallets(self, stack):
        topup = await paid(stack, 500_000)
        await stack.app.withdrawals.journal.debit(ALICE, "spend", 300_000, "q-1")
        await dispute_event(stack, topup)
        await dispute_event(stack, topup, "lost", event="dispute.updated")
        view = (await reconciliation(stack).run()).view()
        assert view["disputes"] == {
            "count": 1, "open": 0, "openKobo": 0, "writtenOffKobo": 300_000, "feesUsd": 15,
        }  # fmt: skip
        assert view["owedKobo"] == 0


class TestTheGap:
    async def test_holding_less_than_it_owes_is_short_by_the_difference(self, stack):
        await owe(stack, ALICE, 1_000_000)
        report = await reconciliation(stack, bachs=400_000, paystack=300_000, vtpass=200_000).run()
        assert (report.gap_kobo, report.short) == (100_000, True)
        assert report.view()["heldKobo"] == {"bachs": 400_000, "paystack": 300_000, "vtpass": 200_000}
        assert audited(stack, "wallet.reconcile.short")[0]["gap_kobo"] == 100_000

    async def test_holding_more_than_it_owes_is_not_short(self, stack):
        await owe(stack, ALICE, 1_000_000)
        report = await reconciliation(stack, bachs=2_000_000).run()
        assert (report.gap_kobo, report.short) == (-1_000_000, False)

    async def test_a_bachs_balance_a_lost_dispute_took_below_zero_counts_against_234(self, stack):
        await owe(stack, ALICE, 100_000)
        report = await reconciliation(stack, bachs=-50_000, paystack=100_000).run()
        assert report.gap_kobo == 50_000 and report.short

    @pytest.mark.parametrize(
        ("bachs", "paystack", "vtpass", "unread"),
        [
            (BachsError("Bachs could not be reached.", retryable=True), 0, 0, "bachs"),
            (0, PaystackError("Paystack could not be reached.", retryable=True), 0, "paystack"),
            (0, 0, LookupError("VTpass could not be reached."), "vtpass"),
        ],
    )
    async def test_a_provider_that_cannot_be_read_is_unknown_never_zero(
        self, stack, bachs, paystack, vtpass, unread
    ):
        await owe(stack, ALICE, 1_000_000)
        report = await reconciliation(stack, bachs, paystack, vtpass).run()
        assert report.gap_kobo is None and not report.short
        assert report.view()["heldKobo"][unread] is None
        assert [line["provider"] for line in audited(stack, "wallet.reconcile.unread")] == [unread]

    async def test_a_vtpass_check_that_failed_is_not_read_as_a_balance(self, stack):
        class Refused(Balance):
            async def check_access(self) -> AccessCheck:
                return AccessCheck(False, reason="VTpass refused the credentials.", balance_kobo=9_000_000)

        audit = Audit([stack.audit_lines.append], stack.clock)
        treasury = Treasury(Balance(0), Balance(0), Refused(0), audit)
        await owe(stack, ALICE, 1_000_000)
        report = await Reconciliation(stack.db, stack.clock, treasury, audit).run()
        assert report.held.vtpass_kobo is None and report.gap_kobo is None


class TestFundingIsPausedWhileShort:
    async def test_a_short_run_refuses_new_top_ups_and_opens_none(self, stack):
        await owe(stack, ALICE, 1_000_000)
        assert (await reconciliation(stack).run()).funding_paused
        with pytest.raises(DomainError) as refused:
            await started(stack)
        assert refused.value.code == "FUNDING_PAUSED"
        assert await stack.rows("SELECT id FROM wallet_topup") == []

    async def test_a_complete_run_that_is_not_short_opens_them_again(self, stack):
        await owe(stack, ALICE, 1_000_000)
        await reconciliation(stack).run()
        assert not (await reconciliation(stack, bachs=1_000_000).run()).funding_paused
        assert (await started(stack)).state == "open"

    async def test_a_run_that_cannot_read_a_provider_leaves_the_pause_as_it_was(self, stack):
        await owe(stack, ALICE, 1_000_000)
        await reconciliation(stack).run()
        unread = BachsError("Bachs could not be reached.", retryable=True)
        assert (await reconciliation(stack, bachs=unread, paystack=5_000_000).run()).funding_paused
        await reconciliation(stack, bachs=1_000_000).run()
        assert not (await reconciliation(stack, bachs=unread).run()).funding_paused

    async def test_spending_and_withdrawing_are_not_paused(self, stack):
        await owe(stack, ALICE, 1_000_000)
        await reconciliation(stack).run()
        assert await stack.app.withdrawals.journal.debit(ALICE, "spend", 100_000, "q-1") is not None


class TestWhenItRuns:
    async def test_the_cron_runs_it_once_an_hour(self, stack):
        await stack.app.background.minute()
        await stack.app.background.minute()
        assert await stack.count("wallet_reconciliation") == 1
        stack.clock.advance(EVERY_MS / 1000)
        await stack.app.background.minute()
        assert await stack.count("wallet_reconciliation") == 2

    async def test_the_simulated_providers_hold_what_they_say(self, stack):
        report = await stack.app.reconciliation.run()
        assert report.held.bachs_kobo == 0
        assert report.held.paystack_kobo is not None and report.held.vtpass_kobo is not None


class TestTheOpsRoute:
    async def test_an_operator_runs_it_now_and_reads_the_report(self, stack):
        await owe(stack, ALICE, 100_000)
        answer = await handle(
            stack.app, "GET", "/ops/wallet/reconcile", {"authorization": f"Bearer {TOKEN}"}, b""
        )
        assert answer.status == 200
        report = json.loads(answer.body)
        assert report["owedKobo"] == 100_000 and report["disputes"]["feesUsd"] == 0
        assert await stack.count("wallet_reconciliation") == 1

    @pytest.mark.parametrize(
        ("method", "headers", "status"),
        [("GET", {}, 404), ("GET", {"authorization": "Bearer wrong"}, 404),
         ("POST", {"authorization": f"Bearer {TOKEN}"}, 405)],
    )  # fmt: skip
    async def test_only_an_operator_gets_it_and_only_by_get(self, stack, method, headers, status):
        answer = await handle(stack.app, method, "/ops/wallet/reconcile", headers, b"")
        assert answer.status == status
        assert await stack.count("wallet_reconciliation") == 0


class TestEachRunIsKept:
    async def test_a_run_is_never_changed_or_removed(self, stack):
        await reconciliation(stack).run()
        for sql in ("UPDATE wallet_reconciliation SET at = at + 1", "DELETE FROM wallet_reconciliation"):
            with pytest.raises(sqlite3.IntegrityError):
                await stack.db.execute(sql)

    @pytest.mark.parametrize(("gap", "short"), [(100, 0), (-100, 1), (None, 1)])
    async def test_a_run_says_short_exactly_when_its_gap_is_above_zero(self, stack, gap, short):
        with pytest.raises(sqlite3.IntegrityError):
            await stack.db.execute(
                "INSERT INTO wallet_reconciliation (at, owed_kobo, bachs_kobo, paystack_kobo, vtpass_kobo, "
                "gap_kobo, withdrawing_kobo, disputes, open_disputes, open_disputed_kobo, written_off_kobo, "
                "short) VALUES (0, ?, ?, 0, 0, ?, 0, 0, 0, 0, 0, ?)",
                100, None if gap is None else 100 - gap, gap, short,
            )  # fmt: skip
