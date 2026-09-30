# SPDX-License-Identifier: AGPL-3.0-or-later
"""A long chat driven over HTTP and a WebSocket, the way a page drives it: turns, and what the person does
with the cards (approve and pay, decline, the notes the card leaves for the model). Used by the Worker tests
of compaction and by the real-model probe."""

import asyncio
import contextlib
import hashlib
import hmac
import json
from typing import Any

import httpx

from .worker_client import Visitor, finished, ws_events

WEBHOOK_SECRET = "dummy-local-webhook-secret"
RATE_WAITS = 40
RATE_WAIT_SECONDS = 3
SMALL_TALK = (
    "How far? Abeg remind me wetin you fit do for me, I no sabi all these things well well",
    "Good morning, I hope the network dey work today. My brother said his own dey slow o",
    "Oga no wahala, I go check am later. Just tell me if you fit do another network too",
    "Thanks, that was quick. Abeg how much be the cheapest data plan wey dey for MTN this week?",
    "I dey fine, thank you. Please keep it short, I dey on the bus and the signal no too strong",
    "Can you explain the steps again? I am not sure I followed what the card asked me to do",
    "Alright. One of my customers said she would settle tomorrow, I will remind her by message",
    "No problem at all, take your time. I am just checking a few things before I continue",
)
PADDING = (
    "I have been thinking about how I handle money for the shop, because some weeks go well and some weeks "
    "do not, and I would like to keep things simple so that I do not lose track of what I have spent.",
    "My sister says I should write everything down every evening but I never find the time, and then on "
    "Sunday I sit with a pen and try to remember, and of course half of it is gone by then.",
    "Last month a customer came with a big order and I had to rush to the market, so I am still trying to "
    "work out whether I made any profit at all or whether it only felt like a good month.",
)


def talk(n: int) -> str:
    return f"{SMALL_TALK[n % len(SMALL_TALK)]}. {PADDING[n % len(PADDING)]} (message {n})"[:480]


class LongChat:
    def __init__(self, v: Visitor, chat: str, ws: Any) -> None:
        self.v, self.chat, self._stream = v, chat, ws_events(ws)
        self.events: list[dict[str, Any]] = []

    @classmethod
    @contextlib.asynccontextmanager
    async def open(cls, v: Visitor, first: str = "Good morning"):
        """A chat made by its first message, followed from its first event."""
        chat = await v.new_chat()
        assert (await v.send(chat, first)).status_code == 200
        async with v.socket(chat) as ws:
            long = cls(v, chat, ws)
            await long._until(finished, 120)
            yield long

    async def _until(self, done, timeout: float) -> None:
        async with asyncio.timeout(timeout):
            async for event in self._stream:
                self.events.append(event)
                if done(event):
                    return

    async def say(self, text: str, timeout: float = 120) -> list[dict[str, Any]]:
        """Sends a message and returns the events up to the end of the turn that answered it."""
        start = len(self.events)
        answer = await self.v.send(self.chat, text)
        for _ in range(RATE_WAITS):
            if answer.status_code != 429:
                break
            await asyncio.sleep(RATE_WAIT_SECONDS)
            answer = await self.v.send(self.chat, text)
        assert answer.status_code == 200, answer.text
        seq = answer.json()["seq"]
        await self._until(lambda e: finished(e) and e["seq"] > seq, timeout)
        return self.events[start:]

    def cards(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == "card"]

    async def call(self, card: dict[str, Any], name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        quote = card["payload"]["result"]["structuredContent"]["quote"]
        token = card["payload"]["result"]["_meta"]["approvalToken"]
        full = {"quote_id": quote["id"], "approval_token": token, **arguments}
        answer = await self.v.post(
            f"/c/{self.chat}/call", {"server": card["payload"]["server"], "name": name, "arguments": full}
        )
        assert answer.status_code == 200, answer.text
        return answer.json()

    async def note(self, card: dict[str, Any], phase: str) -> None:
        """What the card tells the model when it reaches a finished state."""
        quote = card["payload"]["result"]["structuredContent"]["quote"]
        text = (
            f"The person's card for quote {quote['id']} ({quote['amount']['display']}) now shows: {phase}. "
        )
        assert (await self.v.post(f"/c/{self.chat}/context", {"text": text})).status_code == 200

    async def decline(self, card: dict[str, Any]) -> None:
        await self.call(card, "decline_quote", {})
        await self.note(card, "declined")

    async def pay(self, card: dict[str, Any]) -> None:
        """Approve, pay at the simulated bank, and let the payment webhook reach the card."""
        quote = card["payload"]["result"]["structuredContent"]["quote"]
        approved = await self.call(
            card,
            "approve_quote",
            {"displayed_amount_kobo": quote["amount"]["kobo"], "readback_confirmed": True},
        )
        checkout = approved["structuredContent"]["quote"]["checkoutUrl"]
        async with httpx.AsyncClient() as bank:
            await bank.post(checkout.rstrip("/") + "/pay")
            body = json.dumps({"quote_id": quote["id"]}).encode()
            hook = await bank.post(
                f"{self.v.base}/hooks/payment",
                content=body,
                headers={"X-Signature": signature(body)},
            )
            assert hook.json() == {"pushed": True}
        await self._until(
            lambda e: e["type"] == "card_state" and e["ref"] == quote["id"] and _phase(e) == "succeeded", 20
        )
        await self.note(card, "succeeded")

    def compactions(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == "compaction"]


def signature(body: bytes) -> str:
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _phase(event: dict[str, Any]) -> str:
    return event["payload"]["result"]["structuredContent"]["quote"]["phase"]
