# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Durable Object's WebSocket, against the running Worker: a cursor, several sockets, a socket that
sleeps while the object hibernates, and a payment webhook pushed to an open card without any polling."""

import asyncio
import json

import httpx
import pytest

from chat import tickets

from .worker_client import HOST, Visitor, finished, reset_budget, until, ws_events

pytestmark = pytest.mark.worker
WEBHOOK_SECRET = "dummy-local-webhook-secret"
CHECKOUT = "http://localhost:8900"


@pytest.fixture(autouse=True)
async def fresh_budget():
    await reset_budget()


async def read_until(ws, predicate, timeout=30):
    return await until(ws_events(ws), predicate, timeout)


async def test_a_socket_gets_the_replay_then_the_live_events_and_the_same_log_as_the_stream():
    async with Visitor() as v:
        chat = await v.new_chat()
        await v.send(chat, "slow:20@0.1")
        await asyncio.sleep(0.6)
        async with v.socket(chat, since=0) as ws:
            live = await read_until(ws, finished)
        assert [e["seq"] for e in live] == list(range(1, len(live) + 1))
        assert live == await v.log(chat)


async def test_a_socket_that_reconnects_at_its_cursor_gets_no_gap_and_no_repeat():
    async with Visitor() as v:
        chat = await v.new_chat()
        await v.send(chat, "slow:60@0.1")
        async with v.socket(chat) as ws:
            first = await read_until(ws, lambda e: e["seq"] >= 8)
        await asyncio.sleep(1)
        async with v.socket(chat, since=first[-1]["seq"]) as ws:
            rest = await read_until(ws, finished)
        assert [e["seq"] for e in first + rest] == list(range(1, len(first + rest) + 1))
        assert first + rest == await v.log(chat)


async def test_several_sockets_and_a_stream_see_one_log():
    async with Visitor() as v:
        chat = await v.new_chat()
        await v.send(chat, "slow:30@0.1")
        async with v.socket(chat) as one, v.socket(chat) as two:
            a, b, c = await asyncio.gather(
                read_until(one, finished), read_until(two, finished), until(v.sse(chat), finished)
            )
        assert a == b == c


async def test_a_socket_is_refused_without_a_ticket_or_from_another_site():
    async with Visitor() as v:
        chat = await v.new_chat()
        await v.send(chat, "hello")
        cookies = "; ".join(f"{k}={v_}" for k, v_ in v.http.cookies.items())
        import websockets

        base = HOST.replace("http", "ws", 1)
        for url, origin in ((f"{base}/c/{chat}/ws", HOST), (f"{base}/c/{chat}/ws?ticket=nope", HOST)):
            with pytest.raises(websockets.exceptions.InvalidStatus) as refused:
                await websockets.connect(url, origin=origin, additional_headers={"Cookie": cookies})
            assert refused.value.response.status_code == 403
        ticket = (await v.post(f"/c/{chat}/ticket")).json()["path"]
        with pytest.raises(websockets.exceptions.InvalidStatus):
            await websockets.connect(
                base + ticket, origin="http://evil.example", additional_headers={"Cookie": cookies}
            )


async def test_a_stranger_gets_no_ticket_for_someones_chat():
    async with Visitor() as owner, Visitor() as stranger:
        chat = await owner.new_chat()
        await owner.send(chat, "hello")
        assert (await stranger.post(f"/c/{chat}/ticket")).status_code == 404


async def test_a_payment_webhook_reaches_a_socket_that_slept_through_the_objects_hibernation():
    async with Visitor() as v:
        chat = await v.new_chat()
        await v.send(chat, "Pay ₦2,500 to Demo Kitchen for lunch")
        events = await until(v.sse(chat), finished)
        card = next(e for e in events if e["type"] == "card")
        result, quote = card["payload"]["result"], card["payload"]["result"]["structuredContent"]["quote"]
        approved = await v.post(
            f"/c/{chat}/call",
            {
                "server": card["payload"]["server"],
                "name": "approve_quote",
                "arguments": {
                    "quote_id": quote["id"],
                    "approval_token": result["_meta"]["approvalToken"],
                    "displayed_amount_kobo": quote["amount"]["kobo"],
                },
            },
        )
        checkout_url = approved.json()["structuredContent"]["quote"]["checkoutUrl"]
        last_seq = (await v.log(chat))[-1]["seq"]
        async with v.socket(chat, since=last_seq) as ws:
            await asyncio.sleep(25)  # long enough for the object to be evicted and its socket kept
            async with httpx.AsyncClient() as bank:
                await bank.post(checkout_url.rstrip("/") + "/pay")
            body = json.dumps({"quote_id": quote["id"]}).encode()
            hook = await httpx.AsyncClient().post(
                f"{HOST}/hooks/payment", content=body, headers={"X-Signature": tickets_sign(body)}
            )
            assert hook.json() == {"pushed": True}
            pushed = await read_until(ws, lambda e: e["type"] == "card_state", timeout=5)
        phases = [e["payload"]["result"]["structuredContent"]["quote"]["phase"] for e in pushed]
        assert phases == ["succeeded"]


def tickets_sign(body: bytes) -> str:
    return tickets.sign_webhook(body, WEBHOOK_SECRET)
