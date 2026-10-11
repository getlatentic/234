# SPDX-License-Identifier: AGPL-3.0-or-later
"""Holds a crash left behind (wallet/stale_holds.py): the minute cron gives back a hold that paid no quote
once it is past its time, never a hold whose claim landed and never a fresh one, oldest first and a bounded
number a run; and a claim that lands late and the release exclude each other."""

import asyncio

from checkout.ledger import ClaimTerms
from checkout.owner import DEFAULT_OWNER
from checkout.wallet import stale_holds
from checkout.wallet.spending import HOLD_LIVE, WALLET_PAID
from tests.airtime_support import approve, code_of, quote_input
from tests.wallet_support import entries, fund, journal_of

STALE_SECONDS = stale_holds.HOLD_STALE_MS / 1000


async def _quote(stack, **over):
    return await stack.airtime.create_airtime_quote(**quote_input(**over))


async def _orphaned_hold(stack, **over):
    """A hold taken and then nothing: the Worker stopped before the claim."""
    issued = await _quote(stack, **over)
    quote = await stack.ledger.get(issued.quote["id"])
    await stack.app.contexts["airtime"].wallet.hold(DEFAULT_OWNER, quote)
    return quote


async def _balance(stack) -> int:
    return await journal_of(stack).balance(DEFAULT_OWNER)


def _reaped(stack) -> int:
    return sum('"wallet.hold.released_stale"' in line for line in stack.audit_lines)


async def _claim(stack, quote_id):
    return await stack.ledger.claim_approval(quote_id, "airtime", ClaimTerms(WALLET_PAID, HOLD_LIVE))


class TestTheMinuteGivesBackStaleHolds:
    async def test_a_stale_hold_is_released_and_audited(self, stack):
        await fund(stack, 200_000)
        quote = await _orphaned_hold(stack)
        stack.clock.advance(STALE_SECONDS)
        await stack.app.background.minute()
        assert [e["ref"] for e in await entries(stack, "release")] == [quote.id]
        assert await _balance(stack) == 200_000
        assert _reaped(stack) == 1

    async def test_a_fresh_hold_is_left_alone(self, stack):
        await fund(stack, 200_000)
        await _orphaned_hold(stack)
        stack.clock.advance(STALE_SECONDS - 1)
        await stack.app.background.minute()
        assert await entries(stack, "release") == []
        assert await _balance(stack) == 150_000

    async def test_a_hold_whose_claim_landed_is_never_released(self, stack):
        await fund(stack, 200_000)
        delivered = await _quote(stack)
        await stack.airtime.approve(
            delivered.quote["id"], delivered.approval_token, 50_000, True, funding="wallet"
        )
        pending = await _quote(stack, phone="201000000000")
        await stack.airtime.approve(
            pending.quote["id"], pending.approval_token, 50_000, True, funding="wallet"
        )
        stack.clock.advance(3600)
        await stack.app.background.minute()
        assert await entries(stack, "release") == []
        assert await _balance(stack) == 100_000

    async def test_a_hold_on_a_quote_approved_for_the_checkout_is_given_back(self, stack):
        await fund(stack, 200_000)
        issued = await _quote(stack)
        await stack.app.contexts["airtime"].wallet.hold(
            DEFAULT_OWNER, await stack.ledger.get(issued.quote["id"])
        )
        await approve(stack.airtime, issued)
        stack.clock.advance(STALE_SECONDS)
        await stack.app.background.minute()
        assert await _balance(stack) == 200_000

    async def test_a_released_hold_is_not_released_again(self, stack):
        await fund(stack, 200_000)
        await _orphaned_hold(stack)
        stack.clock.advance(STALE_SECONDS)
        await stack.app.background.minute()
        assert await stack.app.background.stale_holds.release_due() == 0
        assert _reaped(stack) == 1


class TestEachRunIsBounded:
    async def test_the_oldest_holds_go_first(self, stack, monkeypatch):
        monkeypatch.setattr(stale_holds, "RELEASE_LIMIT", 2)
        await fund(stack, 500_000)
        made = []
        for _ in range(3):
            made.append(await _orphaned_hold(stack))
            stack.clock.advance(1)
        stack.clock.advance(STALE_SECONDS)
        assert await stack.app.background.stale_holds.release_due() == 2
        assert [e["ref"] for e in await entries(stack, "release")] == [q.id for q in made[:2]]

    async def test_paid_holds_never_crowd_out_a_stale_one(self, stack, monkeypatch):
        monkeypatch.setattr(stale_holds, "RELEASE_LIMIT", 2)
        await fund(stack, 500_000)
        for _ in range(3):
            issued = await _quote(stack)
            await stack.airtime.approve(
                issued.quote["id"], issued.approval_token, 50_000, True, funding="wallet"
            )
        orphan = await _orphaned_hold(stack)
        stack.clock.advance(STALE_SECONDS)
        await stack.app.background.minute()
        assert [e["ref"] for e in await entries(stack, "release")] == [orphan.id]


class TestALateClaimAndTheReaper:
    async def test_the_reaper_first_and_the_claim_loses(self, stack):
        await fund(stack, 200_000)
        quote = await _orphaned_hold(stack)
        stack.clock.advance(STALE_SECONDS)
        await stack.app.background.minute()
        assert await code_of(_claim(stack, quote.id)) == "APPROVAL_IN_PROGRESS"
        assert (await stack.ledger.get(quote.id)).state == "open"
        assert await _balance(stack) == 200_000

    async def test_the_claim_first_and_the_reaper_gives_nothing_back(self, stack):
        await fund(stack, 200_000)
        quote = await _orphaned_hold(stack)
        stack.clock.advance(STALE_SECONDS)
        _, claimed = await _claim(stack, quote.id)
        assert claimed
        await stack.app.background.minute()
        assert await entries(stack, "release") == []
        assert await _balance(stack) == 150_000

    async def test_racing_leaves_exactly_one_outcome(self, stack):
        await fund(stack, 1_000_000)
        for _ in range(6):
            quote = await _orphaned_hold(stack)
            stack.clock.advance(STALE_SECONDS)
            await asyncio.gather(
                stack.app.background.stale_holds.release_due(),
                _claim(stack, quote.id),
                return_exceptions=True,
            )
            approved = (await stack.ledger.get(quote.id)).progress.get("funding") == "wallet"
            released = await journal_of(stack).entry(DEFAULT_OWNER, "release", quote.id) is not None
            assert approved != released, "the quote is paid from its hold, or the hold is given back"
        spent = await stack.rows(
            "SELECT COUNT(*) AS n FROM quotes WHERE json_extract(progress, '$.funding') = 'wallet'"
        )
        assert await _balance(stack) == 1_000_000 - 50_000 * spent[0]["n"]
