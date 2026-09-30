# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the ledger guarantees when callers race: one claim, one winner of a once-only write, and a daily
limit that racing approvals cannot both fit under. The last test is the control: it approves by reading and
then writing, and overspends, so the others can fail."""

import asyncio

from checkout.owner import acting_for
from tests.ledger_support import new_quote
from tests.support import ALICE, BOB


async def test_gathered_approvals_of_one_quote_claim_once(app):
    quote, _ = await app.ledger.create(new_quote())
    results = await asyncio.gather(*[app.ledger.claim_approval(quote.id, "paystack-pay") for _ in range(10)])
    assert sum(claimed for _, claimed in results) == 1


async def test_progress_is_set_once_by_exactly_one_of_many_racing_callers(app):
    quote, _ = await app.ledger.create(new_quote())
    wrote = await asyncio.gather(
        *[app.ledger.set_progress_once(quote.id, "orderPlacedAt", i) for i in range(20)]
    )
    assert sum(wrote) == 1
    assert (await app.ledger.get(quote.id)).progress["orderPlacedAt"] == wrote.index(True)


async def test_a_step_is_acquired_by_exactly_one_of_many_racing_callers(app):
    quote, _ = await app.ledger.create(new_quote())
    won = await asyncio.gather(*[app.ledger.acquire_step(quote.id, 30_000) for _ in range(20)])
    assert sum(won) == 1


async def _eight_quotes_of_thirty_thousand(app):
    ids = []
    for i in range(8):
        quote, _ = await app.ledger.create(new_quote(3_000_000, f"race-{i:08d}"))
        ids.append(quote.id)
    return ids


async def _approved_kobo(app) -> int:
    row = await app.db.row(
        "SELECT COALESCE(SUM(amount_kobo), 0) AS kobo FROM quotes WHERE state = 'approved'"
    )
    return row["kobo"]


async def test_concurrent_approvals_cannot_exceed_the_daily_limit(app):
    ids = await _eight_quotes_of_thirty_thousand(app)
    results = await asyncio.gather(
        *[app.ledger.claim_approval(i, "paystack-pay") for i in ids for _ in range(3)], return_exceptions=True
    )
    assert await _approved_kobo(app) == 9_000_000 <= app.ledger.limits.daily_kobo
    assert sum(1 for r in results if isinstance(r, tuple) and r[1]) == 3
    assert all(
        getattr(r, "code", "LIMIT_DAILY") == "LIMIT_DAILY" for r in results if isinstance(r, Exception)
    )


async def test_the_read_then_write_control_does_overspend_so_the_test_above_can_fail(app):
    from checkout.naive import naive_approve

    ids = await _eight_quotes_of_thirty_thousand(app)
    await asyncio.gather(*[naive_approve(app.ledger, i) for i in ids])
    assert await _approved_kobo(app) > app.ledger.limits.daily_kobo


async def _quotes_of(app, owner: str, prefix: str) -> list[str]:
    with acting_for(owner):
        made = [await app.ledger.create(new_quote(3_000_000, f"{prefix}-{i:07d}")) for i in range(8)]
    return [quote.id for quote, _ in made]


async def _approved_kobo_of(app, owner: str) -> int:
    row = await app.db.row(
        "SELECT COALESCE(SUM(amount_kobo), 0) AS kobo FROM quotes WHERE state = 'approved' AND owner = ?",
        owner,
    )
    return row["kobo"]


async def _claim_as(app, owner: str, quote_id: str):
    with acting_for(owner):
        return await app.ledger.claim_approval(quote_id, "paystack-pay")


async def test_two_owners_approving_together_each_fill_their_own_daily_limit_and_no_more(app):
    alices, bobs = await _quotes_of(app, ALICE, "alice"), await _quotes_of(app, BOB, "bob")
    work = [(ALICE, q) for q in alices for _ in range(3)] + [(BOB, q) for q in bobs for _ in range(3)]
    results = await asyncio.gather(*[_claim_as(app, o, q) for o, q in work], return_exceptions=True)

    limit = app.ledger.limits.daily_kobo
    assert await _approved_kobo_of(app, ALICE) == 9_000_000 <= limit
    assert await _approved_kobo_of(app, BOB) == 9_000_000 <= limit
    claimed = [
        (owner, r) for (owner, _), r in zip(work, results, strict=True) if isinstance(r, tuple) and r[1]
    ]
    won = {owner: sum(1 for o, _ in claimed if o == owner) for owner in (ALICE, BOB)}
    assert won == {ALICE: 3, BOB: 3}
    refusals = [r for r in results if isinstance(r, Exception)]
    assert refusals and all(getattr(r, "code", "") == "LIMIT_DAILY" for r in refusals)


async def test_one_owners_racing_approvals_never_exceed_their_own_limit_while_another_is_spending(app):
    alices, bobs = await _quotes_of(app, ALICE, "alice"), await _quotes_of(app, BOB, "bob")
    await asyncio.gather(
        *[_claim_as(app, BOB, q) for q in bobs[:2]],
        *[_claim_as(app, ALICE, q) for q in alices for _ in range(4)],
        return_exceptions=True,
    )
    assert await _approved_kobo_of(app, ALICE) == 9_000_000
    assert await _approved_kobo_of(app, BOB) == 6_000_000


async def test_the_read_then_write_control_overspends_each_owner_so_the_per_owner_test_can_fail(app):
    from checkout.naive import naive_approve

    alices, bobs = await _quotes_of(app, ALICE, "alice"), await _quotes_of(app, BOB, "bob")

    async def naive_as(owner: str, quote_id: str):
        with acting_for(owner):
            return await naive_approve(app.ledger, quote_id)

    await asyncio.gather(*[naive_as(ALICE, q) for q in alices], *[naive_as(BOB, q) for q in bobs])
    limit = app.ledger.limits.daily_kobo
    assert await _approved_kobo_of(app, ALICE) > limit
    assert await _approved_kobo_of(app, BOB) > limit
