# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `brands` connector, served by the host itself: the hub sends it the same MCP requests it sends a remote
connector (tools/list, tools/call, resources/list, resources/read), with the ledger owner key it names every
call with, and, for a model's call, whether that owner is a signed-in account (ACCOUNT_META). The model may
list the Brands and send one a message; a sign-in card asks how its sign-in stands. Only an account can let
234 act for it at a Brand, so that it can see and end that in Connected apps (accounts/connected.py)."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from ..db import Db
from ..hub import ACCOUNT_META, MIME_TYPE, HubError
from ..settings import Settings
from . import agent
from .config import SERVER, ReachSettings, reach_settings
from .directory import Brand, Directory
from .receipts import ReceiptRefused, Receipts
from .signing_in import SigningIn
from .store import Store
from .wire import BrandError, BrandUnavailable, Reply, TokenRejected, send

CARD_URI = f"ui://{SERVER}/card.html"
CARD_FILE = Path(__file__).with_name("card.html")
STALE_CONTEXT = ("INVALID_PARAMS", "UNSUPPORTED_OPERATION")
READ = {"readOnlyHint": True, "openWorldHint": True}
TALK = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}

NOT_AN_ACCOUNT = (
    "{brand} needs the person's permission, and only someone signed in to 234 can give it. Ask them to sign "
    "in, then send the request again."
)

TOOLS = [
    {
        "name": "list_brands",
        "description": "The Brands whose own assistants 234 can talk to for the person, what each does, and "
        "what the person has let 234 do on their account there.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": READ,
        "_meta": {"ui": {"visibility": ["model"]}},
    },
    {
        "name": "message_brand",
        "description": "Sends one message to a Brand's own assistant for the person and returns its reply. "
        "Pass the person's request in their words. The conversation with each Brand continues until "
        "new_conversation is true. If the Brand needs the person's permission, the result says so and shows "
        "the person a card to sign in at the Brand; after they say they signed in, send the request again.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "brand": {"type": "string", "description": "The Brand's id, as list_brands gives it."},
                "text": {"type": "string", "minLength": 1, "maxLength": 2000},
                "new_conversation": {"type": "boolean"},
            },
            "required": ["brand", "text"],
            "additionalProperties": False,
        },
        "annotations": TALK,
        "_meta": {"ui": {"resourceUri": CARD_URI, "visibility": ["model"]}},
    },
    {
        "name": "sign_in_status",
        "description": "Called by the sign-in card. Not for the model.",
        "inputSchema": {
            "type": "object",
            "properties": {"card_id": {"type": "string", "maxLength": 40}},
            "required": ["card_id"],
            "additionalProperties": False,
        },
        "annotations": READ,
        "_meta": {"ui": {"resourceUri": CARD_URI, "visibility": ["app"]}},
    },
]


def _result(text: str, data: dict[str, Any] | None = None, error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": error}
    if data is not None:
        result["structuredContent"] = data
    return result


class ReachServer:
    def __init__(
        self,
        settings: ReachSettings,
        db: Db,
        client: httpx.AsyncClient,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings, self._client, self._clock = settings, client, clock
        self._store = Store(db)
        self.directory = Directory(settings.reached, client, clock)
        self._signing_in = SigningIn(settings, self._store, client)
        self._receipts = Receipts(client, clock)

    async def request(
        self, method: str, params: dict[str, Any] | None = None, owner: str | None = None, notes: bool = False
    ) -> dict[str, Any]:
        params = params or {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "resources/list":
            return {"resources": [{"uri": CARD_URI, "name": "Sign in at a Brand", "mimeType": MIME_TYPE}]}
        if method == "resources/read" and params.get("uri") == CARD_URI:
            return {"contents": [{"uri": CARD_URI, "mimeType": MIME_TYPE, "text": CARD_FILE.read_text()}]}
        if method == "tools/call" and owner:
            account = (params.get("_meta") or {}).get(ACCOUNT_META) is True
            return await self._call(str(params.get("name")), params.get("arguments") or {}, owner, account)
        raise HubError(f"{method}: not offered by {SERVER}.")

    async def relay(self, *_: Any) -> httpx.Response:
        raise HubError(f"{SERVER} is not reachable from outside the host.")

    async def _call(self, name: str, arguments: dict[str, Any], owner: str, account: bool) -> dict[str, Any]:
        try:
            if name == "list_brands":
                return await self._list(owner)
            if name == "message_brand":
                return await self._message(arguments, owner, account)
            if name == "sign_in_status":
                return await self._status(str(arguments.get("card_id", "")), owner)
        except BrandUnavailable as problem:
            return _result(str(problem), error=True)
        raise HubError(f"There is no tool {name} on {SERVER}.")

    async def _list(self, owner: str) -> dict[str, Any]:
        listed = []
        for brand in await self.directory.brands():
            held = await self._store.delegation(owner, brand.id)
            allowed = (
                [brand.delegation.scopes.get(s, s) for s in held.scopes] if held and brand.delegation else []
            )
            listed.append(
                {"id": brand.id, "name": brand.name, "description": brand.description,
                 "skills": list(brand.skills), "allowed": allowed}
            )  # fmt: skip
        if not listed:
            return _result("No Brand can be reached now.", {"brands": []})
        lines = [f"{b['id']}: {b['name']}. {b['description']}" for b in listed]
        return _result("\n".join(lines), {"brands": listed})

    async def _message(self, arguments: dict[str, Any], owner: str, account: bool) -> dict[str, Any]:
        brand = await self.directory.find(str(arguments.get("brand", "")))
        text = str(arguments.get("text", "")).strip()[:2000]
        if brand is None or not text:
            return _result("Unknown Brand or empty message. Call list_brands for the ids.", error=True)
        if arguments.get("new_conversation"):
            await self._store.forget_context(owner, brand.id)
        reply = await self._exchange(brand, owner, text)
        if reply.missing_scopes and not account:
            said = f"{brand.name} says: {reply.text}\n" if reply.text else ""
            return _result(f"{said}{NOT_AN_ACCOUNT.format(brand=brand.name)}")
        if reply.missing_scopes:
            return await self._ask_to_sign_in(brand, owner, reply)
        return await self._answered(brand, owner, reply)

    async def _exchange(self, brand: Brand, owner: str, text: str, retried: bool = False) -> Reply:
        now = int(self._clock())
        held = await self._signing_in.fresh(brand, owner, now)
        context = await self._store.context(owner, brand.id)
        jwt = agent.token(
            self._settings, brand.reached.audience, agent.sub_for(owner, brand.reached.card_url), now
        )
        try:
            reply = await send(
                self._client, brand.interface_url, jwt, text, context, held.access_token if held else None
            )
        except TokenRejected:
            await self._store.forget_delegation(owner, brand.id)
            if retried:
                raise BrandUnavailable("The Brand refused the person's permission twice.") from None
            return await self._exchange(brand, owner, text, retried=True)
        except BrandError as error:
            if context and error.reason in STALE_CONTEXT and not retried:
                await self._store.forget_context(owner, brand.id)
                return await self._exchange(brand, owner, text, retried=True)
            raise BrandUnavailable(
                f"{brand.name} refused the message: {error.message or error.reason}"
            ) from None
        if reply.context_id:
            await self._store.keep_context(owner, brand.id, reply.context_id, now)
        return reply

    async def _ask_to_sign_in(self, brand: Brand, owner: str, reply: Reply) -> dict[str, Any]:
        if brand.delegation is None:
            return _result(
                f"{brand.name} needs a permission it offers no way to give: {reply.text}", error=True
            )
        now = int(self._clock())
        held = await self._store.delegation(owner, brand.id)
        scopes = tuple(dict.fromkeys([*(held.scopes if held else ()), *reply.missing_scopes]))
        sign_in = await self._signing_in.start(brand, owner, scopes, now)
        asked = [brand.delegation.scopes.get(s, s) for s in reply.missing_scopes]
        card = {"card_id": sign_in.id, "sign_in": self._shown(brand, sign_in.state, sign_in.link)}
        said = f"{brand.name} says: {reply.text}\n" if reply.text else ""
        told = f"{said}{brand.name} needs the person's permission to: {'; '.join(asked)}. "
        return _result(told + "They sign in at the Brand on the card; wait for them to say they did.", card)

    def _shown(self, brand: Brand, state: str, link: str) -> dict[str, Any]:
        """What the card shows: the Brand and its link. The Brand shows what it asks for on its own page."""
        return {"brand": brand.name, "state": state, "link": link}

    async def _answered(self, brand: Brand, owner: str, reply: Reply) -> dict[str, Any]:
        data: dict[str, Any] = {"brand": brand.name, "reply": reply.text}
        note = ""
        if reply.receipt is not None:
            try:
                claims = await self._receipts.verified(reply.receipt, brand, self._settings.issuer)
            except ReceiptRefused as refused:
                note = f"\n(The receipt {brand.name} sent did not check out: {refused}. It was not kept.)"
            else:
                await self._store.keep_receipt(owner, brand.id, reply.receipt, int(self._clock()))
                note = "\n(Its receipt checks out and is kept.)"
                data["receipt"] = {
                    "scopes_used": claims["scopesUsed"],
                    "actions": [a.get("tool") for a in claims["actions"]],
                }
        return _result(f"{brand.name} replied: {reply.text}{note}", data)

    async def end(self, owner: str, brand_id: str) -> bool:
        """Ends what 234 holds for the person at this Brand: it asks the Brand to revoke the grant where the
        Brand offers that, then forgets the tokens and the conversation. Whether the Brand confirmed it."""
        held = await self._store.delegation(owner, brand_id)
        brand = await self.directory.find(brand_id) if held else None
        revoked = False
        if held and brand:
            revoked = await self._signing_in.revoke(brand, owner, held, int(self._clock()))
        await self._store.forget_delegation(owner, brand_id)
        await self._store.forget_context(owner, brand_id)
        return revoked

    async def _status(self, card_id: str, owner: str) -> dict[str, Any]:
        sign_in = await self._store.sign_in(owner, card_id)
        brand = await self.directory.find(sign_in.brand) if sign_in else None
        if sign_in is None or brand is None:
            return _result("This sign-in is not known.", error=True)
        state, ended_now = await self._signing_in.poll(sign_in, brand, int(self._clock() * 1000))
        shown = self._shown(brand, state, sign_in.link)
        shown["interval"] = sign_in.interval
        data: dict[str, Any] = {"card_id": card_id, "sign_in": shown}
        if ended_now and state == "connected":
            data["connected_now"] = True
        return _result(f"Sign-in at {brand.name}: {state}.", data)


def local_servers(settings: Settings, db: Db, client: httpx.AsyncClient) -> dict[str, ReachServer]:
    """The connectors the host serves itself: `brands`, when 234 reaches other Brands."""
    if not settings.reaches:
        return {}
    reach = reach_settings(settings.public_base_url, settings.pact_agent_key, settings.pact_reach)
    return {SERVER: ReachServer(reach, db, client)} if reach else {}
