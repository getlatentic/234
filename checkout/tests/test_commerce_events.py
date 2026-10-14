# SPDX-License-Identifier: AGPL-3.0-or-later
"""An order's ending is told as `quote.finished`, as every quote's is (docs/commerce.md, "Interoperability"):
the same events, to the owner's subscription alone, whichever way the order ended."""

import base64
import json

import pytest

from checkout.audit import Audit
from checkout.events.delivery import Delivery
from checkout.events.service import Events
from checkout.events.subscriptions import Subscriptions
from checkout.jobs import InlineJobs
from checkout.transport import Reply
from tests.commerce_support import answer, approval, as_account, fund, meal
from tests.connector_support import quote_of
from tests.support import ALICE, BOB, ScriptedTransport

SECRET = "whsec_" + base64.b64encode(b"k" * 32).decode()
URL = "https://receiver.example.com/mcp-events/cb_1"


def echo(sent):
    if sent.body.get("type") == "verification":
        return Reply(200, json.dumps({"challenge": sent.body["challenge"]}), "application/json")
    return Reply(200, "{}", "application/json")


@pytest.fixture
def wired(stack):
    transport = ScriptedTransport(echo)
    events = Events(Subscriptions(stack.db), transport, stack.clock, allow_loopback=False)
    delivery = Delivery(stack.db, transport, stack.clock, Audit([stack.audit_lines.append], stack.clock))
    delivery.jobs = InlineJobs(lambda job: delivery.deliver(job["event"], job["subscription"]))
    return events, delivery, transport


async def subscribe(events, owner):
    delivery = {"mode": "webhook", "url": URL, "secret": SECRET}
    return await events.subscribe(
        owner, "merchants", {"name": "quote.finished", "arguments": {}, "delivery": delivery}
    )


async def ordered(stack, outcome: str) -> str:
    await fund(stack, 2_000_000, ALICE)
    made = await as_account(stack, "create_quote", **meal())
    quote_id = quote_of(made)["id"]
    await answer(stack, quote_id, outcome)
    await as_account(stack, "approve_quote", **approval(made, funding="wallet"))
    return quote_id


async def test_a_delivered_order_is_told_to_its_owners_subscription_once(stack, wired):
    events, delivery, transport = wired
    await subscribe(events, ALICE)
    quote_id = await ordered(stack, "delivered")
    assert await delivery.drain() == 1
    (sent,) = [call.body for call in transport.calls if call.body.get("name") == "quote.finished"]
    assert sent["data"] == {
        "quote_id": quote_id,
        "connector": "merchants",
        "state": "settled",
        "amount_kobo": 1_100_000,
        "description": "2 x Jollof rice with fried chicken, 1 x Zobo, 500ml",
    }
    assert await delivery.drain() == 0


async def test_an_order_the_merchant_refused_is_told_as_owed_and_then_as_refunded_to_the_wallet(stack, wired):
    events, delivery, transport = wired
    await subscribe(events, ALICE)
    await ordered(stack, "failed")
    await delivery.drain()
    states = [c.body["data"]["state"] for c in transport.calls if c.body.get("name") == "quote.finished"]
    assert states == ["refund_due", "failed"]


async def test_another_owner_hears_nothing_of_it(stack, wired):
    events, delivery, transport = wired
    await subscribe(events, BOB)
    await ordered(stack, "delivered")
    assert await delivery.drain() == 0
    assert [c.body["type"] for c in transport.calls] == ["verification"]
