# SPDX-License-Identifier: AGPL-3.0-or-later
"""One owner's quotes, spend and keys are invisible to another: the daily limit, lookup, approval and
idempotency are each scoped by the owner of the call."""

from contextlib import suppress

import pytest

from checkout.errors import DomainError
from checkout.ledger import Ledger
from checkout.owner import DEFAULT_OWNER, acting_for
from tests.ledger_support import new_quote
from tests.support import ALICE, BOB

THIRTY_THOUSAND = 3_000_000


async def make_as(app, owner, amount=250_000, key="key-00000001"):
    with acting_for(owner):
        quote, _ = await app.ledger.create(new_quote(amount, key))
    return quote


async def claim_as(app, owner, quote_id, connector="paystack-pay"):
    with acting_for(owner):
        return await app.ledger.claim_approval(quote_id, connector)


async def test_each_owner_has_a_daily_limit_of_their_own(app):
    alices = [await make_as(app, ALICE, THIRTY_THOUSAND, f"alice-{i:07d}") for i in range(4)]
    bobs = [await make_as(app, BOB, THIRTY_THOUSAND, f"bob-{i:09d}") for i in range(4)]
    for quote in alices[:3] + bobs[:3]:
        assert (await claim_as(app, ALICE if quote in alices else BOB, quote.id))[1] is True

    for owner, last in ((ALICE, alices[3]), (BOB, bobs[3])):
        with pytest.raises(DomainError) as refused:
            await claim_as(app, owner, last.id)
        assert refused.value.code == "LIMIT_DAILY"
        with acting_for(owner):
            assert (await app.ledger.budget()).spent_today_kobo == 9_000_000


ONE_LINE = "₦30,000 would take today's approved total above the daily limit of ₦100,000 (₦10,000 left today)."


async def test_the_daily_limit_message_shows_the_owners_own_remainder_at_quote_time_and_at_approval(app):
    over = await make_as(app, ALICE, THIRTY_THOUSAND, "alice-over-01")
    for i in range(3):
        quote = await make_as(app, ALICE, THIRTY_THOUSAND, f"alice-{i:07d}")
        await claim_as(app, ALICE, quote.id)
    await claim_as(app, BOB, (await make_as(app, BOB, THIRTY_THOUSAND, "bob-000000001")).id)
    with pytest.raises(DomainError) as at_approval:
        await claim_as(app, ALICE, over.id)
    with pytest.raises(DomainError) as at_quote, acting_for(ALICE):
        await app.ledger.create(new_quote(THIRTY_THOUSAND, "alice-late-01"))
    assert at_approval.value.message == at_quote.value.message == ONE_LINE


async def test_one_owner_spending_the_whole_day_leaves_another_the_whole_day(app):
    quotes = [await make_as(app, ALICE, 5_000_000, f"alice-{i:07d}") for i in range(2)]
    for quote in quotes:
        await claim_as(app, ALICE, quote.id)
    with acting_for(BOB):
        assert (await app.ledger.budget()).remaining_today_kobo == 10_000_000
    bob = await make_as(app, BOB, 5_000_000, "bob-000000001")
    assert (await claim_as(app, BOB, bob.id))[1] is True


async def test_a_quote_of_another_owner_is_not_found_as_if_it_did_not_exist(app):
    quote = await make_as(app, ALICE)
    with acting_for(BOB):
        assert await app.ledger.get(quote.id) is None
        with pytest.raises(DomainError) as theirs:
            await app.ledger.require(quote.id, "paystack-pay")
        with pytest.raises(DomainError) as nothing:
            await app.ledger.require("qt-00000000000000000000", "paystack-pay")
    assert theirs.value.code == nothing.value.code == "QUOTE_NOT_FOUND"
    assert theirs.value.message.replace(quote.id, "X") == nothing.value.message.replace(
        "qt-00000000000000000000", "X"
    )
    with acting_for(ALICE):
        assert (await app.ledger.get(quote.id)).id == quote.id


async def test_another_owner_cannot_approve_a_quote_even_knowing_its_id(app):
    quote = await make_as(app, ALICE)
    with pytest.raises(DomainError) as refused:
        await claim_as(app, BOB, quote.id)
    assert refused.value.code == "QUOTE_NOT_FOUND"
    assert (await app.db.row("SELECT state, approved_at FROM quotes WHERE id = ?", quote.id)) == {
        "state": "open",
        "approved_at": None,
    }
    assert await app.db.rows("SELECT * FROM quote_events") == []
    assert (await claim_as(app, ALICE, quote.id))[1] is True


@pytest.mark.parametrize(
    "act",
    [
        lambda ledger, q: ledger.transition(q, ("open",), "declined"),
        lambda ledger, q: ledger.patch_progress(q, {"attempt": 9}),
        lambda ledger, q: ledger.set_progress_once(q, "orderPlacedAt", 1),
        lambda ledger, q: ledger.acquire_step(q, 30_000),
        lambda ledger, q: ledger.release_approval(q),
    ],
    ids=["transition", "patch progress", "set once", "acquire step", "release approval"],
)
async def test_another_owner_changes_nothing_of_a_quote_by_any_write(app, act):
    quote = await make_as(app, ALICE)
    before = await app.db.row("SELECT * FROM quotes WHERE id = ?", quote.id)
    with acting_for(BOB), suppress(Exception):  # a refusal or "vanished": either way the row is left alone
        await act(app.ledger, quote.id)
    assert await app.db.row("SELECT * FROM quotes WHERE id = ?", quote.id) == before


async def test_owners_never_share_an_idempotency_key(app):
    alice = await make_as(app, ALICE, 250_000, "the-same-key-1")
    bob = await make_as(app, BOB, 300_000, "the-same-key-1")
    assert alice.id != bob.id and (alice.amount_kobo, bob.amount_kobo) == (250_000, 300_000)
    with acting_for(ALICE):
        again, replayed = await app.ledger.create(new_quote(250_000, "the-same-key-1"))
    assert (again.id, replayed) == (alice.id, True)


async def test_a_key_another_owner_used_is_neither_replayed_nor_a_conflict(app):
    alice = await make_as(app, ALICE, 250_000, "guessable-key-1")
    with acting_for(BOB):
        assert await app.ledger.replay("paystack-pay", "guessable-key-1", "any") is None
        bob, replayed = await app.ledger.create(new_quote(250_000, "guessable-key-1"))
    assert replayed is False and bob.id != alice.id


async def test_a_call_that_says_whose_it_is_never_meets_one_that_does_not(app):
    unnamed, _ = await app.ledger.create(new_quote(250_000, "no-owner-key-1"))
    with acting_for(ALICE):
        assert await app.ledger.get(unnamed.id) is None
    assert (await app.db.row("SELECT owner FROM quotes WHERE id = ?", unnamed.id))["owner"] == DEFAULT_OWNER


async def test_a_ledger_with_no_default_owner_refuses_a_call_that_names_none(app):
    strict = Ledger(app.db, app.clock, app.ledger.limits, 600, "secret", None)
    with pytest.raises(DomainError) as refused:
        await strict.create(new_quote())
    assert refused.value.code == "OWNER_REQUIRED"
    with pytest.raises(DomainError):
        await strict.budget()
    with pytest.raises(DomainError):
        await strict.get("qt-00000000000000000000")
    assert await app.db.rows("SELECT * FROM quotes") == []


async def test_an_owner_cannot_be_changed_after_a_quote_is_made(app):
    quote = await make_as(app, ALICE)
    with pytest.raises(Exception, match="cannot be changed"):
        await app.db.execute("UPDATE quotes SET owner = ? WHERE id = ?", BOB, quote.id)


async def test_the_owner_of_an_expiry_is_the_quotes_own(app, clock):
    quote = await make_as(app, ALICE)
    clock.advance(601)
    with acting_for(BOB):
        assert await app.ledger.get(quote.id) is None
    assert (await app.db.row("SELECT state FROM quotes WHERE id = ?", quote.id))["state"] == "open"
    with acting_for(ALICE):
        assert (await app.ledger.get(quote.id)).state == "expired"


def test_an_owner_is_32_lowercase_hex_characters_and_nothing_else():
    from checkout.owner import is_owner_key

    assert is_owner_key(ALICE) and is_owner_key(DEFAULT_OWNER)
    for bad in ("", "legacy", ALICE.upper(), ALICE + "0", ALICE[:-1], "g" * 32, None, 7, ALICE + "\n"):
        assert not is_owner_key(bad)
    with pytest.raises(ValueError, match="32 lowercase hex"), acting_for("legacy"):
        pass
