# SPDX-License-Identifier: AGPL-3.0-or-later
"""Corrections by an operator (POST /ops/wallet/adjust, wallet/adjustments.py): only with OPS_TOKEN; a debit
never overdraws and never leaves a frozen wallet, a credit is not capped; a correction id writes once and
refuses other terms; above the threshold a second, different operator naming the same terms moves the money;
every proposal, approval and refusal is audited with the operator and the reason, never the token."""

import asyncio
import json

import pytest

from checkout.http import handle
from checkout.wallet.settings import WalletSettings
from checkout.wallet.view import WalletView
from tests.support import ALICE, BOB, make_stack
from tests.withdrawal_support import balance, funded, kinds

TOKEN = "ops-token-not-real-0123456789"
BEARER = {"authorization": f"Bearer {TOKEN}"}
THRESHOLD = 5_000_000


@pytest.fixture
def stack():
    return make_stack(ops_token=TOKEN)


def body(**over) -> dict:
    return {
        "correction_id": "fix-1",
        "owner": ALICE,
        "direction": "credit",
        "amount_kobo": 100_000,
        "reason": "A top-up Bachs settled that never reached the wallet",
        "operator": "ada",
        **over,
    }


async def post(stack, sent, headers=BEARER, method="POST"):
    raw = sent if isinstance(sent, bytes) else json.dumps(sent).encode()
    response = await handle(stack.app, method, "/ops/wallet/adjust", headers, raw)
    return response.status, json.loads(response.body) if response.body.startswith("{") else response.body


async def rows(stack) -> list[dict]:
    return await stack.rows("SELECT * FROM wallet_adjustment ORDER BY correction_id")


def audited(stack, event: str) -> list[dict]:
    return [json.loads(line) for line in stack.audit_lines if f'"event": "{event}"' in line]


class TestOnlyAnOperatorReachesIt:
    async def test_without_a_token_configured_every_call_is_404(self):
        stack = make_stack()
        await funded(stack)
        assert (await post(stack, body(), {"authorization": "Bearer "}))[0] == 404
        assert (await post(stack, body()))[0] == 404
        assert await rows(stack) == []

    async def test_a_wrong_or_missing_token_is_404(self, stack):
        await funded(stack)
        assert (await post(stack, body(), {"authorization": f"Bearer {TOKEN}x"}))[0] == 404
        assert (await post(stack, body(), {}))[0] == 404
        assert await balance(stack) == 10_000_000

    async def test_only_post(self, stack):
        assert (await post(stack, b"", method="GET"))[0] == 405

    async def test_the_token_is_never_audited(self, stack):
        await funded(stack)
        await post(stack, body())
        await post(stack, body(correction_id="fix-2", amount_kobo=-1))
        assert TOKEN not in "\n".join(stack.audit_lines)


class TestTheBody:
    @pytest.mark.parametrize(
        "over",
        [
            {"reason": ""},
            {"reason": "   "},
            {"reason": "x" * 501},
            {"operator": ""},
            {"operator": "o" * 65},
            {"direction": "both"},
            {"amount_kobo": 0},
            {"amount_kobo": -100},
            {"amount_kobo": "100"},
            {"amount_kobo": True},
            {"amount_kobo": 1.5},
            {"owner": "alice"},
            {"correction_id": ""},
            {"correction_id": "has space"},
            {"correction_id": "x" * 65},
        ],
    )
    async def test_is_checked_before_anything_moves(self, stack, over):
        await funded(stack)
        status, answer = await post(stack, body(**over))
        assert (status, answer["error"]["code"]) == (400, "INVALID_INPUT")
        assert await balance(stack) == 10_000_000
        assert await rows(stack) == []

    async def test_a_body_that_is_not_json(self, stack):
        assert (await post(stack, b"{not json"))[0] == 400
        assert (await post(stack, b"[]"))[0] == 400


class TestOneOperatorAtOrBelowTheThreshold:
    async def test_a_credit_is_applied_and_labelled_plainly(self, stack):
        await funded(stack)
        status, answer = await post(stack, body())
        assert status == 200
        assert answer["correction"]["state"] == "applied" and answer["moved"] is True
        assert answer["balanceKobo"] == 10_100_000
        assert await kinds(stack) == ["fund", "adjust"]
        view = await WalletView(stack.app.withdrawals.journal, stack.db).of(ALICE)
        assert view["entries"][0]["label"] == "Correction"
        (line,) = audited(stack, "wallet.adjust.applied")
        assert (line["operator"], line["reason"], line["correction"]) == ("ada", body()["reason"], "fix-1")

    async def test_a_debit_is_applied(self, stack):
        await funded(stack)
        status, _ = await post(stack, body(direction="debit"))
        assert status == 200
        assert await balance(stack) == 9_900_000

    async def test_exactly_the_threshold_needs_one_operator(self, stack):
        await funded(stack)
        assert (await post(stack, body(amount_kobo=THRESHOLD)))[0] == 200

    async def test_a_debit_never_overdraws(self, stack):
        await funded(stack, 50_000)
        status, answer = await post(stack, body(direction="debit"))
        assert (status, answer["error"]["code"]) == (422, "WALLET_SHORT")
        assert await balance(stack) == 50_000
        assert await rows(stack) == []
        assert audited(stack, "wallet.adjust.refused")[0]["why"] == "WALLET_SHORT"

    async def test_a_frozen_wallet_gives_nothing_but_may_be_credited(self, stack):
        await funded(stack)
        await stack.app.withdrawals.journal.set_frozen(ALICE, True)
        status, answer = await post(stack, body(direction="debit"))
        assert (status, answer["error"]["code"]) == (422, "WALLET_FROZEN")
        assert (await post(stack, body(correction_id="fix-2")))[0] == 200
        assert await balance(stack) == 10_100_000

    async def test_a_wallet_frozen_by_a_short_dispute_gives_nothing_either(self, stack):
        await funded(stack)
        await stack.db.execute(
            "INSERT INTO wallet_freeze (owner, reason, ref, created_at) VALUES (?, 'dispute', 'dsp_1', 0)",
            ALICE,
        )
        status, answer = await post(stack, body(direction="debit"))
        assert (status, answer["error"]["code"]) == (422, "WALLET_FROZEN")
        assert await balance(stack) == 10_000_000

    async def test_an_owner_without_a_wallet_is_refused_and_gets_none(self, stack):
        status, answer = await post(stack, body(owner=BOB))
        assert (status, answer["error"]["code"]) == (422, "WALLET_NONE")
        assert await stack.rows("SELECT owner FROM wallet WHERE owner = ?", BOB) == []


class TestOncePerCorrectionId:
    async def test_a_retry_writes_once_and_answers_with_the_first_result(self, stack):
        await funded(stack)
        first = await post(stack, body())
        again = await post(stack, body(operator="bea"))
        assert first[1]["correction"] == again[1]["correction"]
        assert (again[0], again[1]["moved"]) == (200, False)
        assert await kinds(stack) == ["fund", "adjust"]

    @pytest.mark.parametrize(
        "over",
        [{"amount_kobo": 100_001}, {"direction": "debit"}, {"reason": "another reason"}, {"owner": BOB}],
    )
    async def test_the_same_id_with_other_terms_is_refused(self, stack, over):
        await funded(stack)
        await funded(stack, owner=BOB)
        await post(stack, body())
        status, answer = await post(stack, body(**over))
        assert (status, answer["error"]["code"]) == (409, "CORRECTION_CONFLICT")
        assert await kinds(stack) == ["fund", "adjust"]
        assert await kinds(stack, BOB) == ["fund"]

    async def test_racing_retries_write_once(self, stack):
        await funded(stack)
        await asyncio.gather(*[post(stack, body()) for _ in range(6)])
        assert await kinds(stack) == ["fund", "adjust"]

    async def test_racing_corrections_that_cannot_both_fit_do_not_both_land(self, stack):
        await funded(stack, 150_000)
        sent = [post(stack, body(correction_id=f"fix-{n}", direction="debit")) for n in range(4)]
        await asyncio.gather(*sent)
        assert await kinds(stack) == ["fund", "adjust"]
        assert await balance(stack) == 50_000


class TestTwoOperatorsAboveTheThreshold:
    LARGE = THRESHOLD + 1

    async def test_the_first_call_proposes_and_moves_nothing(self, stack):
        await funded(stack)
        status, answer = await post(stack, body(amount_kobo=self.LARGE))
        assert (status, answer["correction"]["state"], answer["moved"]) == (202, "proposed", False)
        assert await kinds(stack) == ["fund"]
        assert audited(stack, "wallet.adjust.proposed")[0]["operator"] == "ada"

    async def test_the_same_operator_again_moves_nothing(self, stack):
        await funded(stack)
        await post(stack, body(amount_kobo=self.LARGE))
        status, answer = await post(stack, body(amount_kobo=self.LARGE))
        assert (status, answer["correction"]["state"]) == (202, "proposed")
        assert await kinds(stack) == ["fund"]
        assert audited(stack, "wallet.adjust.refused")[0]["why"] == "second_operator"

    async def test_a_second_operator_with_other_terms_is_refused(self, stack):
        await funded(stack)
        await post(stack, body(amount_kobo=self.LARGE))
        status, _ = await post(stack, body(amount_kobo=self.LARGE + 1, operator="bea"))
        assert status == 409
        assert (await rows(stack))[0]["state"] == "proposed"
        assert await kinds(stack) == ["fund"]

    async def test_a_second_operator_with_the_same_terms_applies_it_once(self, stack):
        await funded(stack)
        await post(stack, body(amount_kobo=self.LARGE))
        status, answer = await post(stack, body(amount_kobo=self.LARGE, operator="bea"))
        assert (status, answer["moved"]) == (200, True)
        assert (answer["correction"]["proposedBy"], answer["correction"]["approvedBy"]) == ("ada", "bea")
        assert await balance(stack) == 10_000_000 + self.LARGE
        again = await post(stack, body(amount_kobo=self.LARGE, operator="cal"))
        assert (again[0], again[1]["moved"], again[1]["correction"]["approvedBy"]) == (200, False, "bea")
        assert await kinds(stack) == ["fund", "adjust"]
        assert audited(stack, "wallet.adjust.applied")[0]["proposed_by"] == "ada"

    async def test_a_credit_is_not_capped(self, stack):
        await funded(stack, 20_000_000)
        large = body(amount_kobo=30_000_000)
        await post(stack, large)
        assert (await post(stack, {**large, "operator": "bea"}))[0] == 200
        assert await balance(stack) == 50_000_000

    async def test_an_approved_debit_still_never_overdraws(self, stack):
        await funded(stack, 1_000_000)
        large = body(amount_kobo=self.LARGE, direction="debit")
        await post(stack, large)
        status, answer = await post(stack, {**large, "operator": "bea"})
        assert (status, answer["error"]["code"]) == (422, "WALLET_SHORT")
        assert (await rows(stack))[0]["state"] == "proposed"
        await funded(stack, self.LARGE, ref="top-up-2")
        assert (await post(stack, {**large, "operator": "bea"}))[0] == 200
        assert await balance(stack) == 1_000_000

    async def test_racing_second_operators_apply_it_once(self, stack):
        await funded(stack)
        await post(stack, body(amount_kobo=self.LARGE))
        await asyncio.gather(
            *[post(stack, body(amount_kobo=self.LARGE, operator=f"op{n}")) for n in range(6)]
        )
        assert await kinds(stack) == ["fund", "adjust"]
        assert await balance(stack) == 10_000_000 + self.LARGE

    async def test_the_threshold_is_configured(self):
        stack = make_stack(ops_token=TOKEN, wallet=WalletSettings(adjust_two_operators_kobo=50_000))
        await funded(stack)
        assert (await post(stack, body()))[0] == 202
