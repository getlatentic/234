# SPDX-License-Identifier: AGPL-3.0-or-later
"""A browser for the tests that run against the local Workers: a cookie jar, the CSRF token, and readers
for a chat's event stream over server-sent events and over the WebSocket."""

import asyncio
import contextlib
import json
import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import websockets

HOST = os.environ.get("HOST_URL", "http://localhost:8901")
FAKE_MODEL = os.environ.get("MODEL_URL", "http://127.0.0.1:8902")
OPS = {"authorization": "Bearer dummy-local-ops-token"}


def runner_urls() -> dict[str, str]:
    """`RUNNER_URLS=do=http://...,queue=http://...`: every host to run the durability tests against."""
    raw = os.environ.get("RUNNER_URLS")
    if not raw:
        return {"do": HOST}
    return dict(item.split("=", 1) for item in raw.split(","))


@dataclass
class Visitor:
    base: str = HOST
    http: httpx.AsyncClient = field(init=False)
    csrf: str = field(init=False, default="")
    _unstarted: set[str] = field(init=False, default_factory=set)

    def __post_init__(self) -> None:
        self.http = httpx.AsyncClient(base_url=self.base, timeout=30, follow_redirects=False)

    async def __aenter__(self) -> Visitor:
        self.csrf = (await self.http.get("/api/me")).json()["csrf"]
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.http.aclose()

    def another_tab(self) -> Visitor:
        """A second tab of this visitor: the same cookies and CSRF token, its own connections."""
        tab = Visitor(self.base)
        tab.http.cookies.update(self.http.cookies)
        tab.csrf = self.csrf
        return tab

    def _headers(self) -> dict[str, str]:
        return {"X-CSRFToken": self.csrf}

    async def new_chat(self) -> str:
        """An id of the kind the home page mints; the chat exists once its first `send` has been accepted."""
        chat = secrets.token_hex(16)
        self._unstarted.add(chat)
        return chat

    async def send(self, chat: str, text: str, kind: str = "send") -> httpx.Response:
        first = kind == "send" and chat in self._unstarted
        answer = await self.http.post(
            f"/c/{chat}/{'start' if first else kind}", headers=self._headers(), json={"text": text}
        )
        if first and answer.status_code == 200:
            self._unstarted.discard(chat)
        return answer

    async def post(self, path: str, body: dict[str, Any] | None = None) -> httpx.Response:
        return await self.http.post(path, headers=self._headers(), json=body or {})

    async def sse(
        self, chat: str, since: int = 0, last_event_id: int | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        headers = {} if last_event_id is None else {"Last-Event-ID": str(last_event_id)}
        async with self.http.stream(
            "GET", f"/c/{chat}/events", params={"since": since}, headers=headers, timeout=None
        ) as response:
            assert response.status_code == 200, response.status_code
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    yield json.loads(line[6:])

    @contextlib.asynccontextmanager
    async def socket(self, chat: str, since: int = 0):
        ticket = (await self.post(f"/c/{chat}/ticket")).json()["path"]
        cookies = "; ".join(f"{k}={v}" for k, v in self.http.cookies.items())
        url = self.base.replace("http", "ws", 1) + ticket
        async with websockets.connect(url, origin=self.base, additional_headers={"Cookie": cookies}) as ws:
            await ws.send(json.dumps({"attach": since}))
            yield ws

    async def log(self, chat: str) -> list[dict[str, Any]]:
        """The whole log as it stands, by one pass of the event stream."""
        events: list[dict[str, Any]] = []
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(1.5):
                async for event in self.sse(chat):
                    events.append(event)
        return events


async def until(chat_reader, predicate, timeout: float = 30) -> list[dict[str, Any]]:
    """Reads events until the predicate holds for one of them; returns all read."""
    seen: list[dict[str, Any]] = []
    async with asyncio.timeout(timeout):
        async for event in chat_reader:
            seen.append(event)
            if predicate(event):
                break
    return seen


def finished(event: dict[str, Any]) -> bool:
    return event["type"] == "turn.finished"


async def ws_events(ws) -> AsyncIterator[dict[str, Any]]:
    while True:
        frame = json.loads(await ws.recv())
        if "seq" in frame:
            yield frame


async def reset_budget(base: str = HOST) -> None:
    async with httpx.AsyncClient() as admin:
        await admin.post(f"{base}/ops/budget/", headers=OPS, json={"reset": True})
