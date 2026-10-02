# SPDX-License-Identifier: AGPL-3.0-or-later
"""What D1 without transactions must still guarantee, proved with real concurrent requests against
the running Worker and its local D1 (workerd). Run with `pytest -m worker`.

Each test fires its requests together with asyncio.gather, so they interleave at every D1 await.
"""

import asyncio

import pytest

from tests.worker_client import ALICE, BASE_URL, BOB, quote_args, quote_of

pytestmark = pytest.mark.worker

THIRTY_THOUSAND_NAIRA = 3_000_000  # daily limit is N100,000, per payment N50,000


async def summary(worker, owner: str | None = None):
    """The ledger as the test route counts it; `spentTodayKobo` is `owner`'s (the default owner's if none)."""
    query = f"?owner={owner}" if owner else ""
    return (await worker.http.get(f"{BASE_URL}/test/summary{query}")).json()


async def make(worker, key: str, amount_kobo: int = THIRTY_THOUSAND_NAIRA, said: str = "₦30,000"):
    made = await worker.call("create_payment_quote", **quote_args(amount_kobo, said, key))
    return quote_of(made), made["_meta"]["approvalToken"]


def approval(worker, view, token):
    return worker.call(
        "approve_quote",
        quote_id=view["id"],
        approval_token=token,
        displayed_amount_kobo=view["amount"]["kobo"],
    )


async def test_a_quote_is_approved_once_however_many_approve_together(worker):
    view, token = await make(worker, "once-000001")
    results = await asyncio.gather(*[approval(worker, view, token) for _ in range(30)])

    texts = [r["content"][0]["text"] for r in results]
    phases = [quote_of(r)["phase"] for r in results if not r.get("isError")]
    assert all(p == "awaiting_checkout" for p in phases)
    # Losers that arrive while the winner is starting the checkout are told so; nobody else errs.
    assert all(
        t.startswith("APPROVAL_IN_PROGRESS") for t, r in zip(texts, results, strict=True) if r.get("isError")
    )
    assert phases, "at least the winner sees the started checkout"

    state = await summary(worker)
    assert state["claimedEvents"] == {view["id"]: 1}
    assert state["byState"]["approved"]["n"] == 1
    urls = {quote_of(r)["checkoutUrl"] for r in results if not r.get("isError")}
    assert len(urls) == 1, "one checkout was started, whoever asks"


async def test_a_repeated_approval_returns_the_same_result(worker):
    view, token = await make(worker, "again-000001")
    first = quote_of(await approval(worker, view, token))
    second = quote_of(await approval(worker, view, token))
    assert first == second and second["phase"] == "awaiting_checkout"


async def test_the_same_idempotency_key_makes_one_quote_however_many_ask_together(worker):
    results = await asyncio.gather(
        *[worker.call("create_payment_quote", **quote_args(key="same-key-0001")) for _ in range(30)]
    )
    assert not any(r.get("isError") for r in results)
    assert len({quote_of(r)["id"] for r in results}) == 1
    state = await summary(worker)
    assert state["byState"]["open"]["n"] == 1

    other = await worker.call(
        "create_payment_quote",
        **quote_args(amount_kobo=300_000, said="₦3,000", key="same-key-0001"),
    )
    assert other["content"][0]["text"].startswith("IDEMPOTENCY_CONFLICT")


async def test_concurrent_approvals_cannot_exceed_the_daily_limit(worker):
    quotes = [await make(worker, f"daily-{i:06d}") for i in range(8)]
    # Each quote is approved by three callers at once: 24 requests, 8 quotes, room for 3.
    results = await asyncio.gather(*[approval(worker, v, t) for v, t in quotes for _ in range(3)])

    state = await summary(worker)
    approved = state["byState"]["approved"]
    assert approved["n"] == 3
    assert approved["kobo"] == 3 * THIRTY_THOUSAND_NAIRA <= state["dailyLimitKobo"]
    assert state["spentTodayKobo"] == 9_000_000
    assert all(n == 1 for n in state["claimedEvents"].values()) and len(state["claimedEvents"]) == 3
    refused = [r for r in results if r.get("isError") and r["content"][0]["text"].startswith("LIMIT_DAILY")]
    assert len(refused) >= 5 * 1, "each of the five losing quotes was refused at least once"


async def test_the_control_without_the_conditional_update_does_overspend(worker):
    """The proof the test above can fail: the same load against a read-then-write approval."""
    overspent = 0
    for round_ in range(6):
        await worker.http.post(f"{BASE_URL}/test/reset")
        quotes = [await make(worker, f"naive-{round_}{i:05d}") for i in range(8)]
        await asyncio.gather(
            *[worker.http.post(f"{BASE_URL}/test/naive-approve/{v['id']}") for v, _ in quotes]
        )
        state = await summary(worker)
        approved = state["byState"].get("approved", {"kobo": 0})
        if approved["kobo"] > state["dailyLimitKobo"]:
            overspent += 1
    assert overspent >= 1, "the naive approval never overspent, so the load is not concurrent enough"


async def test_a_paid_quote_settles_once_under_concurrent_verification(worker):
    view, token = await make(worker, "settle-00001", 250_000, "₦2,500")
    approved = quote_of(await approval(worker, view, token))
    reference = approved["checkoutUrl"].rsplit("/", 1)[1]
    await worker.http.post(f"{BASE_URL}/sim/checkout/{reference}/pay")
    results = await asyncio.gather(*[worker.call("verify_quote", quote_id=view["id"]) for _ in range(20)])
    assert {quote_of(r)["phase"] for r in results} == {"succeeded"}
    assert (await summary(worker))["byState"]["settled"]["n"] == 1


async def test_a_d1_batch_is_one_transaction(worker):
    answer = (await worker.http.post(f"{BASE_URL}/test/batch-rollback")).json()
    assert "CHECK constraint failed" in answer["error"]
    assert answer["rowsLeft"] == [], "the first insert was rolled back with the failing second"


async def test_two_owners_approving_together_each_fill_their_own_daily_limit_and_no_more(worker):
    alice, bob = worker.as_owner(ALICE), worker.as_owner(BOB)
    alices = [await make(alice, f"a-daily-{i:05d}") for i in range(8)]
    bobs = [await make(bob, f"b-daily-{i:05d}") for i in range(8)]
    # Three callers race for each of the sixteen quotes: 48 requests, room for three quotes each.
    results = await asyncio.gather(
        *[approval(alice, v, t) for v, t in alices for _ in range(3)],
        *[approval(bob, v, t) for v, t in bobs for _ in range(3)],
    )

    for owner in (ALICE, BOB):
        state = await summary(worker, owner)
        assert state["spentTodayKobo"] == 9_000_000 <= state["dailyLimitKobo"]
    state = await summary(worker)
    assert state["byState"]["approved"] == {"n": 6, "kobo": 6 * THIRTY_THOUSAND_NAIRA}
    assert len(state["claimedEvents"]) == 6 and all(n == 1 for n in state["claimedEvents"].values())
    refused = [r for r in results if r.get("isError")]
    assert refused and all(
        r["content"][0]["text"].startswith(("LIMIT_DAILY", "APPROVAL_IN_PROGRESS")) for r in refused
    )


async def test_one_owner_spending_everything_at_once_leaves_the_other_owners_day_whole(worker):
    alice, bob = worker.as_owner(ALICE), worker.as_owner(BOB)
    alices = [await make(alice, f"a-flood-{i:05d}") for i in range(8)]
    await asyncio.gather(*[approval(alice, v, t) for v, t in alices for _ in range(3)])
    assert (await summary(worker, ALICE))["spentTodayKobo"] == 9_000_000
    assert (await summary(worker, BOB))["spentTodayKobo"] == 0
    view, token = await make(bob, "b-after-flood-1", THIRTY_THOUSAND_NAIRA, "₦30,000")
    assert quote_of(await approval(bob, view, token))["phase"] == "awaiting_checkout"


async def test_the_control_overspends_each_owner_so_the_per_owner_test_can_fail(worker):
    """The proof the per-owner tests above can fail: the same load against a read-then-write approval."""
    overspent = {ALICE: 0, BOB: 0}
    for round_ in range(40):
        if min(overspent.values()) >= 1:
            break
        await worker.http.post(f"{BASE_URL}/test/reset")
        made = {
            owner: [await make(worker.as_owner(owner), f"naive-{owner[:2]}{round_}{i:03d}") for i in range(8)]
            for owner in (ALICE, BOB)
        }
        await asyncio.gather(
            *[
                worker.http.post(f"{BASE_URL}/test/naive-approve/{v['id']}?owner={owner}")
                for owner, quotes in made.items()
                for v, _ in quotes
            ]
        )
        for owner in overspent:
            state = await summary(worker, owner)
            overspent[owner] += state["spentTodayKobo"] > state["dailyLimitKobo"]
    assert min(overspent.values()) >= 1, f"the naive approval did not overspend each owner: {overspent}"
