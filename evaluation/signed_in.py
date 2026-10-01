# SPDX-License-Identifier: AGPL-3.0-or-later
"""The signed-in people of a memory run: accounts made in the Firebase Auth emulator of the local stack
(started with AUTH=1), each signed in on a browser of its own through the host's own endpoint, and the notes
each one holds, set up and read through the memory connector the way the host does. No model is involved, and
nothing here touches a real Google account."""

import asyncio
import json
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode

import httpx
from tests.worker_client import Visitor

from accounts.owner import account_owner
from turns.ledger_owner import ledger_owner

LOCAL_ACCOUNT_KEY = "dummy-local-account-key"
EMULATOR_KEY = "fake-api-key-for-the-emulator"
PROTOCOL = "2025-11-25"
MIN_LEASE_SECONDS = 8
"""A browser is held at least this long for a draw: the host answers an account at most twelve messages a
minute, and draws that end in two seconds would send more."""


class SetupFailed(Exception):
    pass


async def memory_call(
    http: httpx.AsyncClient, checkout: str, owner: str, tool: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """One call to the memory connector as `owner`, the way the host makes it, with no model in between."""
    headers = {
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": PROTOCOL,
        "x-ledger-owner": owner,
        "x-memory-owner": owner,
    }
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    answer = (await http.post(f"{checkout}/memory/mcp", json=body, headers=headers)).json()
    result = answer.get("result")
    if result is None or result.get("isError"):
        raise SetupFailed(f"memory {tool}: {json.dumps(answer)[:200]}")
    return result


async def sign_in(visitor: Visitor, emulator: str) -> str:
    """Signs the visitor in as a new account of the emulator; the ledger and memory key of that account."""
    identity = {
        "sub": secrets.token_hex(8),
        "email": f"eval.{secrets.token_hex(4)}@example.com",
        "email_verified": True,
    }
    form = urlencode({"id_token": json.dumps(identity), "providerId": "google.com"})
    async with httpx.AsyncClient(timeout=30) as http:
        signed = await http.post(
            f"http://{emulator}/identitytoolkit.googleapis.com/v1/accounts:signInWithIdp",
            params={"key": EMULATOR_KEY},
            json={
                "postBody": form,
                "requestUri": "http://localhost",
                "returnIdpCredential": True,
                "returnSecureToken": True,
            },
        )
    if signed.status_code != 200:
        raise SetupFailed(
            f"the Auth emulator refused the sign-in: HTTP {signed.status_code}; start the stack with AUTH=1"
        )
    answer = signed.json()
    session = await visitor.post("/auth/session", {"idToken": answer["idToken"]})
    if session.status_code != 200:
        raise SetupFailed(f"the host refused the sign-in: HTTP {session.status_code} {session.text[:100]}")
    return ledger_owner(account_owner(answer["localId"], LOCAL_ACCOUNT_KEY))


async def set_up_notes(checkout: str, owner: str, notes: tuple[dict[str, Any], ...]) -> dict[str, str]:
    """The account has exactly these notes: everything it had is deleted, then each is proposed and saved the
    way a card's Save saves it. The id of each, by its ref."""
    refs: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=30) as http:
        await memory_call(http, checkout, owner, "delete_all_memories", {})
        for note in notes:
            fields = {k: v for k, v in note.items() if k != "ref"}
            made = await memory_call(http, checkout, owner, "remember", fields)
            decision = {
                "proposal_id": made["structuredContent"]["proposal_id"],
                "confirm_token": made["_meta"]["confirmToken"],
            }
            await memory_call(http, checkout, owner, "confirm_memory", decision)
            refs[note["ref"]] = decision["proposal_id"]
    return refs


async def live_notes(checkout: str, owner: str) -> list[str]:
    async with httpx.AsyncClient(timeout=30) as http:
        listed = await memory_call(http, checkout, owner, "list_memories", {})
    return [entry["id"] for entry in listed["structuredContent"]["entries"]]


class Accounts:
    """Signed-in browsers, one for each draw that runs at once, so no two draws share an account's notes. A
    browser is leased for one draw and given back."""

    def __init__(self, host: str, emulator: str, size: int) -> None:
        self._host, self._emulator, self._size = host, emulator, size
        self._free: asyncio.Queue[tuple[Visitor, str]] = asyncio.Queue()
        self._open: list[Visitor] = []

    async def start(self) -> None:
        for _ in range(self._size):
            visitor = await Visitor(self._host).__aenter__()
            self._open.append(visitor)
            self._free.put_nowait((visitor, await sign_in(visitor, self._emulator)))

    async def stop(self) -> None:
        for visitor in self._open:
            await visitor.__aexit__(None, None, None)

    @asynccontextmanager
    async def lease(self) -> AsyncIterator[tuple[Visitor, str]]:
        taken = await self._free.get()
        leased = time.monotonic()
        try:
            yield taken
        finally:
            await asyncio.sleep(max(0.0, MIN_LEASE_SECONDS - (time.monotonic() - leased)))
            self._free.put_nowait(taken)
