# SPDX-License-Identifier: AGPL-3.0-or-later
"""A verified collection becomes a `fund` entry (wallet/topup_credit.py): once, however often and however
concurrently it is delivered; only for the checkout, owner and exact amount 234 made it for; within the cap
as it stands when the money arrives; and a paid top-up always has its entry."""

import asyncio
import json

import pytest

from checkout.wallet.settings import WalletSettings
from tests.support import ALICE, BOB, make_stack
from tests.topup_support import SECRET, audited, balance, deliver, funds, started, state_of, succeeded, topups


@pytest.fixture
def stack():
    return make_stack(approval_secret=SECRET)


async def test_a_collection_credits_the_top_ups_amount_and_marks_it_paid(stack):
    topup = await started(stack, 750_050)
    answer = await deliver(stack, succeeded(topup))
    assert answer.status == 200 and json.loads(answer.body) == {"received": True}
    [entry] = await funds(stack)
    assert (entry["owner"], entry["ref"], entry["amount_kobo"], entry["sign"]) == (
        ALICE,
        topup.id,
        750_050,
        1,
    )
    paid = await topups(stack).get(topup.id)
    assert paid is not None and paid.state == "paid" and paid.paid_at == stack.clock.now()
    assert [line["topup"] for line in audited(stack, "wallet.topup.paid")] == [topup.id]


async def test_a_repeated_delivery_credits_once(stack):
    topup = await started(stack)
    for _ in range(3):
        assert (await deliver(stack, succeeded(topup))).status == 200
    assert len(await funds(stack)) == 1 and await balance(stack) == 500_000
    assert len(audited(stack, "wallet.topup.paid")) == 1


async def test_concurrent_deliveries_credit_once(stack):
    topup = await started(stack)
    answers = await asyncio.gather(*[deliver(stack, succeeded(topup)) for _ in range(12)])
    assert {answer.status for answer in answers} == {200}
    assert len(await funds(stack)) == 1 and await balance(stack) == 500_000
    assert await state_of(stack, topup) == "paid"


async def test_a_delivery_after_a_crash_between_credit_and_paid_marks_it_paid(stack):
    topup = await started(stack)
    await topups(stack).journal.credit(ALICE, "fund", topup.amount_kobo, topup.id)
    assert await state_of(stack, topup) == "open"
    assert (await deliver(stack, succeeded(topup))).status == 200
    assert await state_of(stack, topup) == "paid" and len(await funds(stack)) == 1


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"amount": "5000.01"}, "amount"),
        ({"amount": "4999.99"}, "amount"),
        ({"amount": "5000"}, "amount"),
        ({"amount": 500000}, "amount"),
        ({"amount": "50,000.00"}, "amount"),
        ({"currency": "USD"}, "currency"),
        ({"status": "ACCEPTED"}, "status"),
        ({"status": "OVERPAID"}, "status"),
        ({"checkout_id": "chk_someoneelses"}, "checkout"),
        ({"checkout_id": None}, "checkout"),
        ({"metadata": {}}, "owner"),
        ({"metadata": "wallet_owner"}, "owner"),
    ],
)
async def test_a_collection_that_does_not_match_exactly_credits_nothing_and_is_audited(stack, change, reason):
    topup = await started(stack)
    assert (await deliver(stack, succeeded(topup, **change))).status == 200
    assert await funds(stack) == [] and await state_of(stack, topup) == "open"
    [refused] = audited(stack, "wallet.topup.refused")
    assert (refused["reason"], refused["topup"]) == (reason, topup.id)


async def test_a_collection_naming_another_owners_top_up_pays_nobody(stack):
    alices = await started(stack, owner=ALICE)
    bobs = await started(stack, owner=BOB)
    body = succeeded(bobs, metadata=json.loads(succeeded(alices))["data"]["metadata"])
    await deliver(stack, body)
    assert await funds(stack) == []
    assert audited(stack, "wallet.topup.refused")[0]["reason"] == "owner"


async def test_a_collection_for_a_reference_234_did_not_make_credits_nothing(stack):
    topup = await started(stack)
    for reference in ("wt-0000000000000000000a", "ORD-1041", None):
        assert (await deliver(stack, succeeded(topup, reference=reference))).status == 200
    assert await funds(stack) == []
    assert {line["reason"] for line in audited(stack, "wallet.topup.refused")} == {"unknown"}


async def test_another_event_or_a_body_that_is_not_json_is_acknowledged_and_does_nothing(stack):
    topup = await started(stack)
    other = succeeded(topup).replace(b"collection.succeeded", b"checkout.completed")
    for body in (other, b"not json", b"[]"):
        assert (await deliver(stack, body)).status == 200
    assert await funds(stack) == [] and await state_of(stack, topup) == "open"


async def test_the_cap_is_held_when_the_money_arrives_and_a_refused_credit_is_asked_for_again():
    stack = make_stack(approval_secret=SECRET, wallet=WalletSettings(balance_cap_kobo=1_000_000))
    first, second = await started(stack, 600_000), await started(stack, 600_000)
    assert (await deliver(stack, succeeded(first))).status == 200
    assert (await deliver(stack, succeeded(second))).status == 503
    assert await balance(stack) == 600_000 and await state_of(stack, second) == "open"
    assert [line["topup"] for line in audited(stack, "wallet.topup.over_cap")] == [second.id]
    await topups(stack).journal.debit(ALICE, "spend", 300_000, "qt-spent")
    assert (await deliver(stack, succeeded(second))).status == 200
    assert await balance(stack) == 900_000 and await state_of(stack, second) == "paid"


async def test_a_paid_top_up_cannot_be_reopened_or_change_its_terms(stack):
    topup = await started(stack)
    await deliver(stack, succeeded(topup))
    for sql in (
        "UPDATE wallet_topup SET state = 'expired' WHERE id = ?",
        "UPDATE wallet_topup SET amount_kobo = 1 WHERE id = ?",
        "UPDATE wallet_topup SET owner = 'b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0' WHERE id = ?",
    ):
        with pytest.raises(Exception, match="top-up"):
            await stack.db.execute(sql, topup.id)


async def test_the_audit_holds_no_secret_and_no_full_account_number(stack):
    topup = await started(stack)
    body = succeeded(topup, amount="1.00", payment_method_details={"sender_account_number": "2294879124"})
    await deliver(stack, body)
    await deliver(stack, succeeded(topup))
    text = "\n".join(stack.audit_lines)
    assert "2294879124" not in text and SECRET not in text and ALICE not in text
