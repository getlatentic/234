# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from checkout.errors import DomainError
from checkout.ledger import NewQuote, request_hash
from tests.ledger_support import new_quote


async def test_a_new_quote_is_open_and_fixed(app):
    quote, replayed = await app.ledger.create(new_quote())
    assert (quote.state, replayed, quote.amount_kobo) == ("open", False, 250_000)
    with pytest.raises(Exception, match="cannot be changed"):
        await app.db.execute("UPDATE quotes SET amount_kobo = 1 WHERE id = ?", quote.id)


async def test_the_same_key_and_request_returns_the_same_quote(app):
    first, _ = await app.ledger.create(new_quote())
    again, replayed = await app.ledger.create(new_quote())
    assert (again.id, replayed) == (first.id, True)


async def test_the_same_key_for_another_request_is_refused(app):
    await app.ledger.create(new_quote())
    with pytest.raises(DomainError) as refused:
        await app.ledger.create(new_quote(amount=300_000))
    assert refused.value.code == "IDEMPOTENCY_CONFLICT"


async def test_a_quote_is_approved_once(app):
    quote, _ = await app.ledger.create(new_quote())
    first, claimed = await app.ledger.claim_approval(quote.id, "paystack-pay")
    again, claimed_again = await app.ledger.claim_approval(quote.id, "paystack-pay")
    assert (first.state, claimed, claimed_again, again.approved_at) == (
        "approved",
        True,
        False,
        first.approved_at,
    )
    events = await app.db.rows("SELECT * FROM quote_events WHERE quote_id = ?", quote.id)
    assert [e["event"] for e in events] == ["approval.claimed"]


async def test_the_daily_limit_holds_across_quotes(app):
    ids = [(await app.ledger.create(new_quote(4_000_000, f"key-0000000{i}")))[0].id for i in range(3)]
    first, second = [(await app.ledger.claim_approval(i, "paystack-pay"))[1] for i in ids[:2]]
    with pytest.raises(DomainError) as refused:
        await app.ledger.claim_approval(ids[2], "paystack-pay")
    assert (first, second, refused.value.code) == (True, True, "LIMIT_DAILY")
    assert (await app.ledger.budget()).spent_today_kobo == 8_000_000


async def test_a_quote_over_the_per_payment_limit_is_never_made(app):
    with pytest.raises(DomainError) as refused:
        await app.ledger.create(new_quote(5_000_001))
    assert refused.value.code == "LIMIT_PER_PAYMENT"


async def test_an_expired_quote_cannot_be_approved(app, clock):
    quote, _ = await app.ledger.create(new_quote())
    clock.advance(601)
    with pytest.raises(DomainError) as refused:
        await app.ledger.claim_approval(quote.id, "paystack-pay")
    assert refused.value.code == "QUOTE_EXPIRED"


async def test_progress_merges_without_reading(app):
    quote, _ = await app.ledger.create(new_quote())
    await app.ledger.patch_progress(quote.id, {"attempt": 1, "inFlightSince": 5})
    patched = await app.ledger.patch_progress(quote.id, {"checkoutUrl": "https://x", "inFlightSince": None})
    assert patched.progress == {"attempt": 1, "checkoutUrl": "https://x"}


async def test_only_one_caller_acquires_the_step(app):
    quote, _ = await app.ledger.create(new_quote())
    assert await app.ledger.acquire_step(quote.id, 30_000) is True
    assert await app.ledger.acquire_step(quote.id, 30_000) is False


async def test_a_batch_rolls_back_whole(app):
    quote, _ = await app.ledger.create(new_quote())
    with pytest.raises(Exception, match="cannot be changed"):
        await app.db.batch(
            [
                ("INSERT INTO quote_events (quote_id, event, at) VALUES (?, 'x', 1)", (quote.id,)),
                ("UPDATE quotes SET amount_kobo = 1 WHERE id = ?", (quote.id,)),
            ]
        )
    assert await app.db.rows("SELECT * FROM quote_events") == []


async def test_every_connector_spends_from_one_daily_limit(app):
    pay, _ = await app.ledger.create(new_quote(6_000_000 - 1_000_000, "pay-00000001"))
    other = NewQuote(
        connector="airtime", kind="airtime", amount_kobo=4_000_000, description="Airtime",
        merchant="MTN", merchant_ref=None, details={"kind": "airtime"}, idempotency_key="air-00000001",
        request_hash=request_hash(amount_kobo=4_000_000),
    )  # fmt: skip
    airtime, _ = await app.ledger.create(other)
    third = await app.ledger.create(new_quote(2_000_000, "pay-00000002"))
    await app.ledger.claim_approval(pay.id, "paystack-pay")
    await app.ledger.claim_approval(airtime.id, "airtime")
    with pytest.raises(DomainError) as refused:
        await app.ledger.claim_approval(third[0].id, "paystack-pay")
    assert refused.value.code == "LIMIT_DAILY"


async def test_an_approval_put_back_can_be_claimed_again_and_both_claims_are_recorded(app):
    quote, _ = await app.ledger.create(new_quote())
    await app.ledger.claim_approval(quote.id, "paystack-pay")
    released = await app.ledger.release_approval(quote.id)
    assert (released.state, released.approved_at) == ("open", None)
    again, claimed = await app.ledger.claim_approval(quote.id, "paystack-pay")
    assert (again.state, claimed) == ("approved", True)
    events = await app.db.rows(
        "SELECT event, seq FROM quote_events WHERE quote_id = ? ORDER BY at, seq", quote.id
    )
    assert sorted((e["event"], e["seq"]) for e in events) == [
        ("approval.claimed", 1),
        ("approval.claimed", 2),
        ("approval.released", 1),
    ]


async def test_an_approval_with_a_checkout_started_is_not_put_back(app):
    quote, _ = await app.ledger.create(new_quote())
    await app.ledger.claim_approval(quote.id, "paystack-pay")
    await app.ledger.patch_progress(quote.id, {"checkoutUrl": "https://x"})
    assert (await app.ledger.release_approval(quote.id)).state == "approved"
    assert await app.db.rows("SELECT * FROM quote_events WHERE event = 'approval.released'") == []


async def test_progress_is_patched_only_while_the_quote_is_in_the_asked_state(app):
    quote, _ = await app.ledger.create(new_quote())
    untouched = await app.ledger.patch_progress(quote.id, {"a": 1}, only_state="approved")
    assert untouched.progress == {}
    assert (await app.ledger.patch_progress(quote.id, {"a": 1}, only_state="open")).progress == {"a": 1}


async def test_the_step_lock_carries_the_callers_marker_and_goes_stale(app, clock):
    quote, _ = await app.ledger.create(new_quote())
    assert await app.ledger.acquire_step(quote.id, 30_000, {"transferAttempted": True})
    assert (await app.ledger.get(quote.id)).progress["transferAttempted"] is True
    assert not await app.ledger.acquire_step(quote.id, 30_000)
    clock.advance(31)
    assert await app.ledger.acquire_step(quote.id, 30_000)


async def test_a_quote_made_under_a_higher_limit_is_refused_at_approval_once_the_limit_is_lowered(app):
    from checkout.ledger import Limits

    quote, _ = await app.ledger.create(new_quote(3_000_000))
    app.ledger.limits = Limits(per_payment_kobo=1_000_000, daily_kobo=10_000_000)
    with pytest.raises(DomainError) as refused:
        await app.ledger.claim_approval(quote.id, "paystack-pay")
    assert refused.value.code == "LIMIT_PER_PAYMENT"
    assert (await app.ledger.get(quote.id)).state == "open"


async def test_a_new_quote_stores_what_the_server_was_given_and_reads_back_the_same(app):
    quote, replayed = await app.ledger.create(new_quote(250_000, description="Books"))
    assert (quote.state, replayed, quote.amount_kobo, quote.description, quote.approved_at) == (
        "open", False, 250_000, "Books", None,
    )  # fmt: skip
    assert await app.ledger.get(quote.id) == quote


@pytest.mark.parametrize(
    "column", ["amount_kobo = 1", "description = 'x'", "merchant = 'x'", "currency = 'USD'"]
)
async def test_no_fixed_column_of_a_quote_can_be_changed_even_by_direct_sql(app, column):
    quote, _ = await app.ledger.create(new_quote())
    with pytest.raises(Exception, match="cannot be changed"):
        await app.db.execute(f"UPDATE quotes SET {column} WHERE id = ?", quote.id)
    assert (await app.ledger.get(quote.id)).amount_kobo == 250_000


async def test_idempotency_keys_are_separate_per_connector(app):
    first = new_quote()
    await app.ledger.create(first)
    other = NewQuote(
        "airtime", "airtime", 250_000, "Lunch", "Demo Kitchen", None,
        {"kind": "airtime", "network": "mtn", "phone": "08031234567"}, first.idempotency_key, "another-hash",
    )  # fmt: skip
    _, replayed = await app.ledger.create(other)
    assert replayed is False


async def test_an_amount_exactly_at_the_per_payment_limit_is_accepted(app):
    quote, _ = await app.ledger.create(new_quote(5_000_000))
    assert quote.state == "open"


async def test_approval_reserves_the_spend_and_a_second_claim_changes_nothing(app):
    quote, _ = await app.ledger.create(new_quote(300_000))
    first, claimed = await app.ledger.claim_approval(quote.id, "paystack-pay")
    assert (first.state, claimed, (await app.ledger.budget()).spent_today_kobo) == ("approved", True, 300_000)
    _, again = await app.ledger.claim_approval(quote.id, "paystack-pay")
    assert (again, (await app.ledger.budget()).spent_today_kobo) == (False, 300_000)


@pytest.mark.parametrize("ending", ["settled", "failed"])
async def test_the_first_approval_is_found_again_after_the_quote_ended_and_nothing_changes(app, ending):
    quote, _ = await app.ledger.create(new_quote())
    await app.ledger.claim_approval(quote.id, "paystack-pay")
    await app.ledger.transition(quote.id, ("approved",), ending)
    found, claimed = await app.ledger.claim_approval(quote.id, "paystack-pay")
    assert (found.state, claimed) == (ending, False)


async def test_an_approval_from_another_connector_or_for_an_unknown_quote_is_refused(app):
    quote, _ = await app.ledger.create(new_quote())
    for quote_id, connector, code in (
        (quote.id, "airtime", "WRONG_CONNECTOR"),
        ("qt-nope", "paystack-pay", "QUOTE_NOT_FOUND"),
    ):
        with pytest.raises(DomainError) as refused:
            await app.ledger.claim_approval(quote_id, connector)
        assert refused.value.code == code
    assert (await app.ledger.get(quote.id)).state == "open"


async def test_an_expired_quote_reads_expired_and_reserves_nothing(app, clock):
    quote, _ = await app.ledger.create(new_quote())
    clock.advance(600)
    with pytest.raises(DomainError):
        await app.ledger.claim_approval(quote.id, "paystack-pay")
    assert (await app.ledger.get(quote.id)).state == "expired"
    assert (await app.ledger.budget()).spent_today_kobo == 0


async def test_a_quote_approved_in_time_does_not_expire_later(app, clock):
    quote, _ = await app.ledger.create(new_quote())
    clock.advance(9 * 60)
    await app.ledger.claim_approval(quote.id, "paystack-pay")
    clock.advance(2 * 3600)
    assert (await app.ledger.get(quote.id)).state == "approved"


async def test_a_declined_quote_cannot_be_approved(app):
    quote, _ = await app.ledger.create(new_quote())
    await app.ledger.transition(quote.id, ("open",), "declined")
    with pytest.raises(DomainError) as refused:
        await app.ledger.claim_approval(quote.id, "paystack-pay")
    assert refused.value.code == "QUOTE_NOT_OPEN"


async def test_the_rest_of_the_day_is_checked_when_a_quote_is_made(app):
    for i in range(2):
        quote, _ = await app.ledger.create(new_quote(4_000_000, f"fill-0000000{i}"))
        await app.ledger.claim_approval(quote.id, "paystack-pay")
    budget = await app.ledger.budget()
    assert (budget.spent_today_kobo, budget.remaining_today_kobo) == (8_000_000, 2_000_000)
    with pytest.raises(DomainError) as refused:
        await app.ledger.create(new_quote(3_000_000, "fill-00000009"))
    assert refused.value.code == "LIMIT_DAILY"


async def test_a_failed_or_abandoned_payment_stops_counting_but_one_awaiting_a_refund_keeps_counting(app):
    ids = []
    for i in range(3):
        quote, _ = await app.ledger.create(new_quote(1_000_000, f"count-0000000{i}"))
        await app.ledger.claim_approval(quote.id, "paystack-pay")
        ids.append(quote.id)
    assert (await app.ledger.budget()).spent_today_kobo == 3_000_000
    for quote_id, ending in zip(ids, ("failed", "abandoned", "refund_due"), strict=True):
        await app.ledger.transition(quote_id, ("approved",), ending)
    assert (await app.ledger.budget()).spent_today_kobo == 1_000_000


async def test_a_new_day_starts_at_midnight_in_lagos(app, clock):
    for i in range(2):
        quote, _ = await app.ledger.create(new_quote(5_000_000, f"day-000000{i}"))
        await app.ledger.claim_approval(quote.id, "paystack-pay")
    assert (await app.ledger.budget()).remaining_today_kobo == 0
    clock.advance(14 * 3600)
    assert (await app.ledger.budget()).spent_today_kobo == 0


async def test_a_released_approval_stops_counting_and_can_be_claimed_again(app):
    quote, _ = await app.ledger.create(new_quote(700_000))
    await app.ledger.claim_approval(quote.id, "paystack-pay")
    assert (await app.ledger.release_approval(quote.id)).state == "open"
    assert (await app.ledger.budget()).spent_today_kobo == 0
    assert (await app.ledger.claim_approval(quote.id, "paystack-pay"))[1] is True


async def test_a_move_from_a_state_the_quote_is_not_in_is_refused(app):
    quote, _ = await app.ledger.create(new_quote())
    with pytest.raises(DomainError) as refused:
        await app.ledger.transition(quote.id, ("approved",), "settled")
    assert refused.value.code == "QUOTE_NOT_OPEN"


async def test_a_repeated_move_to_the_same_state_is_done_and_keeps_the_first_record(app):
    quote, _ = await app.ledger.create(new_quote())
    await app.ledger.claim_approval(quote.id, "paystack-pay")
    first = await app.ledger.transition(quote.id, ("approved",), "settled", {"paymentStatus": "success"})
    again = await app.ledger.transition(quote.id, ("approved",), "settled")
    assert (again.settled_at, again.progress["paymentStatus"]) == (first.settled_at, "success")


async def test_progress_merges_without_touching_the_quotes_fixed_fields(app):
    quote, _ = await app.ledger.create(new_quote())
    await app.ledger.patch_progress(quote.id, {"checkoutUrl": "https://checkout.example/x"})
    patched = await app.ledger.patch_progress(quote.id, {"paymentStatus": "ongoing"})
    assert patched.progress == {"checkoutUrl": "https://checkout.example/x", "paymentStatus": "ongoing"}
    assert patched.amount_kobo == quote.amount_kobo


async def test_an_approval_token_is_good_for_its_own_quote_only(app):
    a, _ = await app.ledger.create(new_quote(key="tok-00000001"))
    b, _ = await app.ledger.create(new_quote(key="tok-00000002"))
    token = app.ledger.approval_token(a.id)
    assert app.ledger.check_approval_token(a.id, token)
    assert not app.ledger.check_approval_token(b.id, token)
    assert not app.ledger.check_approval_token(a.id, "")
    tampered = token[:-1] + ("1" if token.endswith("0") else "0")
    assert not app.ledger.check_approval_token(a.id, tampered)
    assert not app.ledger.check_approval_token(a.id, token + "00")


async def test_another_secret_makes_another_token(app):
    from checkout.ledger import Ledger

    other = Ledger(app.db, app.clock, app.ledger.limits, 600, "a-different-secret", None)
    quote, _ = await app.ledger.create(new_quote())
    assert not other.check_approval_token(quote.id, app.ledger.approval_token(quote.id))
