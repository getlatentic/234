# SPDX-License-Identifier: AGPL-3.0-or-later
"""A card's own tool calls: relayed to the connector that served it, and the one way a card opens another.

A card names itself in its calls with `quote_id` (an approval card) or `card_id` (any other card), and only
the tools its own view lists are open to it. A result that carries `_meta.ui.resourceUri` and a quote is a
card asking the host for another card: the host records that card in the log, tells the first one where
things stand, and leaves a short note for the model. The approval token stays in the recorded card and is
never in the note, in what the first card is told, or in anything the model or an A2A caller reads.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from . import kinds
from .db import Db
from .eventlog import EventLog
from .hub import MEMORY_SERVER, Hub, HubError, card_uri_of
from .memory import NOT_AN_ACCOUNT

CARD_FIELDS = ("content", "structuredContent")
SPAWNED = "spawned"
ORDER_READY = "Order ready to approve"
_REF_KEYS = ("quote_id", "card_id", "proposal_id")
_STATE_KEYS = ("quote", "memory")

Note = Callable[[str], Awaitable[dict[str, Any]]]
Owner = Callable[[], Awaitable[str]]
HasMemory = Callable[[], Awaitable[bool]]


def public_result(result: dict[str, Any]) -> dict[str, Any]:
    """A card's result as it is kept and pushed: content and structure, never `_meta` (the token)."""
    return {k: v for k, v in result.items() if k in CARD_FIELDS}


def card_ref(result: dict[str, Any]) -> str | None:
    """What a card is called in the log: the id of its quote, or the `card_id` or `proposal_id` its data
    names."""
    data = result.get("structuredContent") or {}
    ref = (data.get("quote") or {}).get("id") or data.get("card_id") or data.get("proposal_id")
    return ref if isinstance(ref, str) and 0 < len(ref) <= 64 else None


def _ref_of(arguments: dict[str, Any]) -> str:
    refs = [str(arguments[key]) for key in _REF_KEYS if key in arguments]
    if len(refs) != 1:
        raise HubError("A card's call names the card it is for, once.")
    return refs[0]


def _opened_view(server: str, result: dict[str, Any]) -> str | None:
    """The view a result asks the host to open: one of this connector's own, for a quote. Anything else
    it asks for is refused."""
    uri = ((result.get("_meta") or {}).get("ui") or {}).get("resourceUri")
    quote = (result.get("structuredContent") or {}).get("quote") or {}
    if result.get("isError") or uri is None:
        return None
    if not quote.get("id") or not isinstance(uri, str) or not uri.startswith(f"ui://{server}/"):
        raise HubError("The connector asked for a card it cannot open.")
    return uri


class CardCalls:
    def __init__(
        self, db: Db, log: EventLog, hub: Hub, note: Note, owner: Owner, has_memory: HasMemory | None = None
    ) -> None:
        """`owner` says whose money this chat's cards touch: the key of the chat's owner, whoever is
        looking at the card. `has_memory` says whether the chat's owner is an account: only then may a card
        call the memory connector."""
        self._db, self._log, self._hub, self._note, self._owner = db, log, hub, note, owner
        self._has_memory = has_memory
        self._opening = asyncio.Lock()

    async def _card(self, ref: str) -> dict[str, Any] | None:
        row = await self._db.row(
            "SELECT payload FROM chat_event WHERE chat_id = ? AND type = ? AND ref = ?",
            self._log.chat_id, kinds.CARD, ref,
        )  # fmt: skip
        return json.loads(row["payload"]) if row else None

    async def _own_tool(self, server: str, name: str, view: str) -> None:
        listed = next((t for t in await self._hub.tools(server) if t["name"] == name), None)
        if listed is None or card_uri_of(listed) != view:
            raise HubError(f"{name} is not a tool of this card.")

    async def call(self, server: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """The card must be one of this chat's, made by this server, and the tool one its view lists. A
        changed quote is pushed to every client showing the card; a result that opens a card opens it."""
        ref = _ref_of(arguments)
        card = await self._card(ref)
        if card is None or card["server"] != server:
            raise HubError("This chat has no card for that request.")
        await self._own_tool(server, name, card["resource_uri"])
        if server == MEMORY_SERVER and not (self._has_memory and await self._has_memory()):
            raise HubError(NOT_AN_ACCOUNT)
        result = await self._hub.call_app_tool(server, name, arguments, await self._owner())
        if view := _opened_view(server, result):
            return await self._open(ref, server, name, view, result)
        await self.push_state(ref, result)
        return result

    async def refresh(self, quote_id: str) -> bool:
        """Asks the connector how a quote stands (a payment webhook arrived) and pushes it to the card."""
        card = await self._card(quote_id)
        if card is None:
            return False
        try:
            result = await self._hub.call_app_tool(
                card["server"], "verify_quote", {"quote_id": quote_id}, await self._owner()
            )
        except HubError, httpx.HTTPError:
            return False
        await self.push_state(quote_id, result)
        return True

    async def push_state(self, ref: str, result: dict[str, Any]) -> None:
        shown = public_result(result)
        if not any(shown.get("structuredContent", {}).get(key) for key in _STATE_KEYS):
            return
        last = await self._db.row(
            "SELECT payload FROM chat_event WHERE chat_id = ? AND ref = ? AND type IN (?, ?) "
            "ORDER BY seq DESC LIMIT 1",
            self._log.chat_id, ref, kinds.CARD, kinds.CARD_STATE,
        )  # fmt: skip
        known = json.loads(last["payload"])["result"]["structuredContent"] if last else None
        if known != shown["structuredContent"]:
            await self._log.append(kinds.CARD_STATE, {"result": shown}, ref=ref)

    async def _open(
        self, origin: str, server: str, tool: str, view: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        """Records the card the result asks for, once however often and from however many tabs it is asked,
        and says so in the asking card's own state."""
        quote = result["structuredContent"]["quote"]
        told = {
            "content": [{"type": "text", "text": ORDER_READY}],
            "structuredContent": {SPAWNED: {"ref": quote["id"]}},
        }
        async with self._opening:
            if await self._card(quote["id"]) is None:
                kept = {"content": result.get("content"), "structuredContent": result["structuredContent"]}
                if token := (result.get("_meta") or {}).get("approvalToken"):
                    kept["_meta"] = {"approvalToken": token}
                payload = {"server": server, "tool": tool, "resource_uri": view, "result": kept}
                await self._log.append(kinds.CARD, payload, ref=quote["id"])
                await self._log.append(kinds.CARD_STATE, {"result": told}, ref=origin)
                await self._note(_note_for(server, quote))
        return told


def _note_for(server: str, quote: dict[str, Any]) -> str:
    """What the model is told: which quote was made, that the person approves it and it cannot, and how to
    report the outcome. The words after "now shows: " are what the transcript shows the person."""
    amount = (quote.get("amount") or {}).get("display")
    made = f"quote {quote['id']}" + (f" ({amount})" if amount else "")
    return (
        f"The person's menu made {made}. They approve it on its card and you cannot; call "
        f"get_quote_status on the {server} connector to report what happened. "
        f"The card now shows: {ORDER_READY}"
    )
