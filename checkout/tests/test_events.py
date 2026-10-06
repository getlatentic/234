# SPDX-License-Identifier: AGPL-3.0-or-later
"""MCP events: the catalog, subscribing (the callback's challenge, refresh, the owner's scope), the outbox a
quote's ending fills, and delivery (Standard Webhooks signatures, retries, 410 and 413, one sender a row)."""

import base64
import hashlib
import hmac
import json

import pytest

from checkout.audit import Audit
from checkout.events import catalog
from checkout.events.delivery import MAX_ATTEMPTS, Delivery, body_of
from checkout.events.service import CALLBACK_ENDPOINT_ERROR, INVALID_PARAMS, EventError, Events
from checkout.events.signing import key_of, sign
from checkout.events.subscriptions import MAX_TTL_MS, Subscriptions
from checkout.jobs import InlineJobs
from checkout.owner import acting_for
from checkout.transport import Reply, TransportError
from tests.ledger_support import new_quote
from tests.support import ScriptedTransport

ALICE, BOB = "a" * 32, "b" * 32
SECRET = "whsec_" + base64.b64encode(b"k" * 32).decode()
URL = "https://receiver.example.com/mcp-events/cb_1"


def echo(sent):
    if sent.body.get("type") == "verification":
        return Reply(200, json.dumps({"challenge": sent.body["challenge"]}), "application/json")
    return Reply(200, "{}", "application/json")


def params(**changes):
    asked = {
        "name": "quote.finished",
        "arguments": {},
        "delivery": {"mode": "webhook", "url": URL, "secret": SECRET},
    }
    return {**asked, **changes}


@pytest.fixture
def wired(stack):
    transport = ScriptedTransport(echo)
    events = Events(Subscriptions(stack.db), transport, stack.clock, allow_loopback=False)
    delivery = Delivery(stack.db, transport, stack.clock, Audit([stack.audit_lines.append], stack.clock))
    delivery.jobs = InlineJobs(lambda job: delivery.deliver(job["event"], job["subscription"]))
    return events, delivery, transport


async def ended(stack, owner, state="declined", key="key-00000001"):
    with acting_for(owner):
        quote, _ = await stack.ledger.create(new_quote(key=key))
        await stack.ledger.transition(quote.id, ("open",), state)
    return quote.id


def test_the_catalog_offers_quote_finished_by_webhook_with_its_schemas():
    (event,) = [catalog.definition("airtime")]
    assert event["name"] == "quote.finished" and event["delivery"] == ["webhook"]
    assert event["inputSchema"]["properties"] == {"quote_id": event["inputSchema"]["properties"]["quote_id"]}
    assert set(event["payloadSchema"]["required"]) == {
        "quote_id",
        "connector",
        "state",
        "amount_kobo",
        "description",
    }


def test_signing_is_standard_webhooks():
    key = b"k" * 32
    expected = base64.b64encode(hmac.new(key, b"evt_1.1700000000.{}", hashlib.sha256).digest()).decode()
    assert sign(SECRET, "evt_1", 1700000000, "{}") == f"v1,{expected}"


@pytest.mark.parametrize(
    "secret",
    [
        "k" * 40,
        "whsec_not base64!",
        "whsec_" + base64.b64encode(b"short").decode(),
        "whsec_" + base64.b64encode(b"x" * 65).decode(),
    ],
)
def test_a_secret_that_is_not_whsec_and_24_to_64_bytes_is_refused(secret):
    with pytest.raises(ValueError):
        key_of(secret)


async def test_subscribing_verifies_the_callback_then_returns_a_stable_id(stack, wired):
    events, _, transport = wired
    first = await events.subscribe(ALICE, "airtime", params())
    challenge = transport.calls[0]
    assert (
        challenge.body["type"] == "verification" and challenge.headers["x-mcp-subscription-id"] == first["id"]
    )
    assert challenge.headers["webhook-signature"].startswith("v1,")
    assert first["cursor"] is None and first["truncated"] is False and first["refreshBefore"].endswith("Z")
    stack.clock.advance(60)
    again = await events.subscribe(ALICE, "airtime", params())
    assert again["id"] == first["id"] and len(transport.calls) == 1, "a refresh is not challenged again"
    assert again["refreshBefore"] > first["refreshBefore"]


@pytest.mark.parametrize(
    "reply", [Reply(200, '{"challenge": "wrong"}'), Reply(500, ""), Reply(302, ""), TransportError("down")]
)
async def test_a_callback_that_does_not_answer_the_challenge_is_refused_and_nothing_is_kept(stack, reply):
    transport = ScriptedTransport(lambda sent: reply)
    events = Events(Subscriptions(stack.db), transport, stack.clock, allow_loopback=False)
    with pytest.raises(EventError) as refused:
        await events.subscribe(ALICE, "airtime", params())
    assert refused.value.code == CALLBACK_ENDPOINT_ERROR and refused.value.data["reason"]
    assert await stack.db.rows("SELECT * FROM event_subscriptions") == []


@pytest.mark.parametrize(
    "url",
    [
        "http://receiver.example.com/cb",
        "https://127.0.0.1/cb",
        "https://localhost/cb",
        "https://10.0.0.8/cb",
        "https://[::1]/cb",
        "https://u:p@receiver.example.com/cb",
        "https://intranet/cb",
        None,
    ],
)
async def test_a_callback_must_be_https_on_a_public_host_name(stack, wired, url):
    events, _, transport = wired
    with pytest.raises(EventError) as refused:
        await events.subscribe(
            ALICE, "airtime", params(delivery={"mode": "webhook", "url": url, "secret": SECRET})
        )
    assert refused.value.code == CALLBACK_ENDPOINT_ERROR and transport.calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "quote.created"},
        {"arguments": {"other": 1}},
        {"arguments": {"quote_id": 5}},
        {"delivery": {"mode": "poll", "url": URL, "secret": SECRET}},
        {"delivery": {"mode": "webhook", "url": URL}},
        {"ttlMs": -1},
        {"ttlMs": "soon"},
    ],
)
async def test_a_malformed_subscription_is_invalid_params(stack, wired, changes):
    events, _, _ = wired
    with pytest.raises(EventError) as refused:
        await events.subscribe(ALICE, "airtime", params(**changes))
    assert refused.value.code == INVALID_PARAMS


async def test_the_lifetime_is_capped_at_30_days_and_indefinite_is_not_granted(stack, wired):
    events, _, _ = wired
    answer = await events.subscribe(ALICE, "airtime", params(ttlMs=10**15))
    (row,) = await stack.db.rows("SELECT expires_at FROM event_subscriptions")
    assert row["expires_at"] == stack.clock.now() + MAX_TTL_MS and answer["refreshBefore"]


async def test_a_quote_that_ends_is_sent_to_its_owners_subscription_signed_and_only_once(stack, wired):
    events, delivery, transport = wired
    sub = (await events.subscribe(ALICE, "paystack-pay", params()))["id"]
    quote_id = await ended(stack, ALICE)
    assert await delivery.drain() == 1
    sent = transport.calls[-1]
    assert sent.url == URL and sent.body["name"] == "quote.finished" and sent.body["cursor"] is None
    assert sent.body["data"] == {
        "quote_id": quote_id,
        "connector": "paystack-pay",
        "state": "declined",
        "amount_kobo": 250000,
        "description": "Lunch",
    }
    body = json.dumps(sent.body, separators=(",", ":"))
    stamp = int(sent.headers["webhook-timestamp"])
    assert sent.headers["webhook-signature"] == sign(SECRET, sent.headers["webhook-id"], stamp, body)
    assert sent.headers["webhook-id"] == sent.body["eventId"] and sent.headers["x-mcp-subscription-id"] == sub
    assert await delivery.drain() == 0, "delivered once"


async def test_another_owner_another_connector_and_another_quote_hear_nothing(stack, wired):
    events, delivery, transport = wired
    await events.subscribe(BOB, "paystack-pay", params())
    await events.subscribe(ALICE, "airtime", params())
    await events.subscribe(ALICE, "paystack-pay", params(arguments={"quote_id": "qt-not-this-one"}))
    await ended(stack, ALICE)
    assert await delivery.drain() == 0
    assert [c.body["type"] for c in transport.calls] == ["verification"] * 3


async def test_a_quote_that_expires_is_an_event_too(stack, wired):
    events, delivery, transport = wired
    await events.subscribe(ALICE, "paystack-pay", params())
    with acting_for(ALICE):
        quote, _ = await stack.ledger.create(new_quote())
        stack.clock.advance(24 * 3600)
        await stack.ledger.get(quote.id)
    await delivery.drain()
    assert transport.calls[-1].body["data"]["state"] == "expired"


async def test_a_failure_is_tried_again_later_with_the_same_event_id_then_given_up(stack):
    answers = iter([])

    def flaky(sent):
        return echo(sent) if sent.body.get("type") == "verification" else next(answers, Reply(503, ""))

    transport = ScriptedTransport(flaky)
    events = Events(Subscriptions(stack.db), transport, stack.clock, allow_loopback=False)
    delivery = Delivery(stack.db, transport, stack.clock, Audit([stack.audit_lines.append], stack.clock))
    delivery.jobs = InlineJobs(lambda job: delivery.deliver(job["event"], job["subscription"]))
    await events.subscribe(ALICE, "paystack-pay", params())
    await ended(stack, ALICE)
    ids = set()
    for _ in range(MAX_ATTEMPTS):
        await delivery.drain()
        ids.add(transport.calls[-1].headers["webhook-id"])
        stack.clock.advance(3600)
    assert len(ids) == 1 and len(transport.calls) == 1 + MAX_ATTEMPTS
    stack.clock.advance(3600)
    assert await delivery.drain() == 0, "given up after the last attempt"


async def test_410_ends_the_subscription_and_413_drops_only_the_event(stack):
    for status, kept in ((410, 0), (413, 1)):
        transport = ScriptedTransport(
            lambda sent, s=status: echo(sent) if sent.body.get("type") else Reply(s, "")
        )
        events = Events(Subscriptions(stack.db), transport, stack.clock, allow_loopback=False)
        delivery = Delivery(stack.db, transport, stack.clock, Audit([stack.audit_lines.append], stack.clock))
        delivery.jobs = InlineJobs(lambda job, d=delivery: d.deliver(job["event"], job["subscription"]))
        await events.subscribe(
            ALICE,
            "paystack-pay",
            params(delivery={"mode": "webhook", "url": f"{URL}{status}", "secret": SECRET}),
        )
        await ended(stack, ALICE, key=f"key-0000{status}")
        await delivery.drain()
        rows = await stack.db.rows("SELECT * FROM event_subscriptions WHERE url = ?", f"{URL}{status}")
        assert len(rows) == kept
        assert await delivery.drain() == 0


async def test_an_expired_subscription_hears_nothing(stack, wired):
    events, delivery, transport = wired
    await events.subscribe(ALICE, "paystack-pay", params(ttlMs=1000))
    stack.clock.advance(5)
    await ended(stack, ALICE)
    await delivery.drain()
    assert [c.body.get("type") for c in transport.calls] == ["verification"]


async def test_two_drains_at_once_send_an_event_once(stack, wired):
    import asyncio

    events, delivery, transport = wired
    await events.subscribe(ALICE, "paystack-pay", params())
    await ended(stack, ALICE)
    await asyncio.gather(delivery.drain(), delivery.drain())
    assert sum(1 for c in transport.calls if "eventId" in c.body) == 1


async def test_unsubscribing_stops_delivery_and_is_idempotent(stack, wired):
    events, delivery, _ = wired
    await events.subscribe(ALICE, "paystack-pay", params())
    asked = params()
    del asked["delivery"]["secret"]
    assert await events.unsubscribe(ALICE, "paystack-pay", asked) == {}
    assert await events.unsubscribe(ALICE, "paystack-pay", asked) == {}
    await ended(stack, ALICE)
    assert await delivery.drain() == 0


async def test_one_owner_cannot_unsubscribe_another(stack, wired):
    events, delivery, _ = wired
    await events.subscribe(ALICE, "paystack-pay", params())
    asked = params()
    await events.unsubscribe(BOB, "paystack-pay", asked)
    await ended(stack, ALICE)
    assert await delivery.drain() == 1


def test_the_event_body_is_the_spec_shape():
    row = {"event_id": "evt_q_settled", "occurred_at": 1_700_000_000_000, "data": '{"quote_id": "q"}'}
    assert json.loads(body_of(row)) == {
        "eventId": "evt_q_settled",
        "name": "quote.finished",
        "timestamp": "2023-11-14T22:13:20.000Z",
        "data": {"quote_id": "q"},
        "cursor": None,
    }


@pytest.mark.parametrize("connector, offered", [("airtime", True), ("paystack-pay", True), ("memory", False)])
async def test_a_money_connector_offers_events_and_memory_does_not(app, connector, offered):
    from checkout.http import handle

    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"},
        },
    }
    answer = await handle(
        app, "POST", f"/{connector}/mcp", {"content-type": "application/json"}, json.dumps(init).encode()
    )
    assert ("events" in json.loads(answer.body)["result"]["capabilities"]) is offered
    listed = {"jsonrpc": "2.0", "id": 2, "method": "events/list", "params": {}}
    answer = await handle(
        app, "POST", f"/{connector}/mcp", {"content-type": "application/json"}, json.dumps(listed).encode()
    )
    assert ("result" in json.loads(answer.body)) is offered
