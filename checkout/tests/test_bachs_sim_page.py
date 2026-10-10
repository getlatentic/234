# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated Bachs checkout page (sim_bachs.py), end to end: a top-up started, paid on the stand-in, and
credited through the same /hooks/bachs code a real delivery takes; an expired one cannot be paid there."""

import re

import pytest

from checkout.bachs.settings import BachsSettings
from checkout.http import handle
from checkout.wallet.topups import TOPUP_MINUTES
from tests.support import ScriptedTransport, json_reply, make_stack
from tests.topup_support import (
    SANDBOX_KEY,
    SECRET,
    WEBHOOK_SECRET,
    audited,
    balance,
    deliver,
    funds,
    started,
    state_of,
    succeeded,
)


def texts(html: str) -> list[str]:
    body = re.sub(r"<(style|script)>.*?</\1>", "", html, flags=re.S)
    return [t.strip() for t in re.split(r"<[^>]+>", body) if t.strip()]


async def page(stack, topup, action=None, headers=None):
    path = f"/sim/bachs/{topup.provider_ref}" + (f"/{action}" if action else "")
    return await handle(stack.app, "POST" if action else "GET", path, headers or {}, b"")


@pytest.fixture
def stack():
    return make_stack(approval_secret=SECRET)


async def test_a_top_up_paid_on_the_stand_in_is_credited_once(stack):
    topup = await started(stack, 250_000)
    opened = await page(stack, topup)
    assert opened.status == 200
    assert texts(opened.body) == [
        "Simulated Bachs checkout",
        "Simulated: no money moves",
        "Add money to your 234 wallet",
        "₦2,500",
        "Pay by bank transfer",
        "Close without paying",
    ]
    paid = await page(stack, topup, "pay")
    assert texts(paid.body)[-1] == "Paid"
    assert await balance(stack) == 250_000 and await state_of(stack, topup) == "paid"
    await page(stack, topup, "pay")
    assert len(await funds(stack)) == 1 and len(audited(stack, "wallet.topup.paid")) == 1


async def test_closing_the_page_pays_nothing(stack):
    topup = await started(stack)
    closed = await page(stack, topup, "close")
    assert texts(closed.body)[-1] == "Closed"
    assert await funds(stack) == [] and await state_of(stack, topup) == "open"


async def test_an_expired_top_up_cannot_be_paid_on_the_stand_in(stack):
    topup = await started(stack)
    stack.clock.advance(TOPUP_MINUTES * 60)
    await stack.app.background.minute()
    assert await state_of(stack, topup) == "expired"
    answer = await page(stack, topup, "pay")
    assert texts(answer.body)[-1] == "Expired"
    assert await funds(stack) == [] and await state_of(stack, topup) == "expired"


async def test_a_genuine_collection_for_an_expired_top_up_is_still_credited(stack):
    topup = await started(stack)
    stack.clock.advance(TOPUP_MINUTES * 60 + 120)
    await stack.app.background.minute()
    assert (await deliver(stack, succeeded(topup))).status == 200
    assert await balance(stack) == 500_000 and await state_of(stack, topup) == "paid"
    assert audited(stack, "wallet.topup.paid")[0]["late"] is True


async def test_a_press_from_another_page_is_refused(stack):
    topup = await started(stack)
    answer = await page(stack, topup, "pay", {"origin": "https://evil.example"})
    assert answer.status == 403 and await funds(stack) == []


@pytest.mark.parametrize("path", ["/sim/bachs/chk_unknown", "/sim/bachs/chk_unknown/pay"])
async def test_an_unknown_checkout_is_not_found(stack, path):
    method = "POST" if path.endswith("pay") else "GET"
    assert (await handle(stack.app, method, path, {}, b"")).status == 404


async def test_an_unknown_button_is_not_found(stack):
    topup = await started(stack)
    assert (await page(stack, topup, "refund")).status == 404


async def test_the_stand_in_is_not_served_in_sandbox_mode():
    created = {"checkout_id": "chk_1", "checkout_url": "https://checkout.bachs.io/c/1", "status": "open",
               "expires_at": "2026-09-29T11:00:00Z", "created_at": "2026-09-29T10:00:00Z"}  # fmt: skip
    stack = make_stack(
        approval_secret=SECRET,
        bachs=BachsSettings("sandbox", SANDBOX_KEY, WEBHOOK_SECRET),
        transport=ScriptedTransport(lambda sent: json_reply(created, 201)),
    )
    topup = await started(stack)
    assert (await page(stack, topup)).status == 404
    assert (await page(stack, topup, "pay")).status == 404
    assert await funds(stack) == []
