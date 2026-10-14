# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Paystack Index that answers from local state: the OAuth server of its published metadata (dynamic client
registration, the authorization code with PKCE S256, refresh with rotation, client credentials, optional
revocation) and its MCP endpoint (Streamable HTTP, protocol 2025-03-26, server `paystack-index` 0.0.1) with the
ten tools of its listing. It is a `Transport`, so 234's real client talks to it unchanged. The page where a
person signs in is served by the Worker (sim_index_page.py), because a browser opens it. It contacts no one."""

import base64
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl

from ...clock import Clock
from ...transport import Reply
from .oauth import challenge_of
from .sim_store import IndexSimStore
from .sim_tool_list import TOOLS
from .sim_tools import run
from .sim_tools_base import SimContext
from .wire import PROTOCOL_VERSION, SESSION_HEADER

JSON = "application/json"
SERVER = {"name": "paystack-index", "version": "0.0.1"}
REVOCATION_SETTING = "revocation"
SSE_SETTING = "sse"
PUBLIC_TOOLS = frozenset({"browse_merchants"})


def _json(status: int, body: Any, headers: Mapping[str, str] | None = None) -> Reply:
    return Reply(status, json.dumps(body), JSON, dict(headers or {}))


def _oauth_error(code: str, description: str = "", status: int = 400) -> Reply:
    return _json(status, {"error": code, "error_description": description})


class IndexSimulator:
    def __init__(self, store: IndexSimStore, clock: Clock, base: str) -> None:
        """`base` is where the simulator's addresses begin, for example http://localhost:8787/sim/index."""
        self._store, self._clock, self._base = store, clock, base.rstrip("/")

    async def send(
        self, method: str, url: str, *, headers: Mapping[str, str], body: str | None, timeout_seconds: float
    ) -> Reply:
        path = url.removeprefix(self._base)
        lowered = {key.lower(): value for key, value in headers.items()}
        match method, path:
            case "GET", "/.well-known/oauth-authorization-server":
                return await self._metadata()
            case "POST", "/oauth/register":
                return await self._register(body or "")
            case "POST", "/oauth/token":
                return await self._token(body or "", lowered)
            case "POST", "/oauth/revoke":
                return await self._revoke(body or "")
            case "POST", "/mcp":
                return await self._mcp(body or "", lowered)
            case _:
                return _json(404, {"error": "not_found"})

    async def _metadata(self) -> Reply:
        found: dict[str, Any] = {
            "issuer": self._base,
            "authorization_endpoint": f"{self._base}/authorize",
            "token_endpoint": f"{self._base}/oauth/token",
            "registration_endpoint": f"{self._base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
            "scopes_supported": ["mcp:transact"],
        }
        if await self._store.setting(REVOCATION_SETTING, "") == "1":
            found["revocation_endpoint"] = f"{self._base}/oauth/revoke"
        return _json(200, found)

    async def _register(self, body: str) -> Reply:
        try:
            asked = json.loads(body)
            uris = [str(u) for u in asked["redirect_uris"]]
        except ValueError, KeyError, TypeError:
            return _oauth_error("invalid_client_metadata", "redirect_uris are required")
        client, secret = await self._store.register_client(uris)
        return _json(
            201,
            {
                "client_id": client,
                "client_secret": secret,
                "redirect_uris": uris,
                "token_endpoint_auth_method": "client_secret_post",
                "grant_types": ["authorization_code", "refresh_token"],
            },
        )

    async def _client(self, form: dict[str, str], headers: dict[str, str]) -> dict[str, Any] | None:
        client_id, secret = form.get("client_id", ""), form.get("client_secret")
        if headers.get("authorization", "").startswith("Basic "):
            try:
                client_id, _, secret = base64.b64decode(headers["authorization"][6:]).decode().partition(":")
            except ValueError:
                return None
        found = await self._store.client(client_id)
        return found if found and found["secret"] == secret else None

    async def _token(self, body: str, headers: dict[str, str]) -> Reply:
        form = dict(parse_qsl(body))
        client = await self._client(form, headers)
        if client is None:
            return _oauth_error("invalid_client", status=401)
        match form.get("grant_type"):
            case "authorization_code":
                return await self._by_code(client, form)
            case "refresh_token":
                return await self._by_refresh(client, form)
            case "client_credentials":
                return _json(200, await self._store.issue_tokens(client["client_id"], None, refresh=False))
            case _:
                return _oauth_error("unsupported_grant_type")

    async def _by_code(self, client: dict[str, Any], form: dict[str, str]) -> Reply:
        grant = await self._store.take_code(form.get("code", ""))
        verifier = form.get("code_verifier", "")
        if (
            grant is None
            or grant["client_id"] != client["client_id"]
            or grant["redirect_uri"] != form.get("redirect_uri")
            or challenge_of(verifier) != grant["challenge"]
        ):
            return _oauth_error("invalid_grant", "The code is not valid.")
        return _json(200, await self._store.issue_tokens(client["client_id"], grant["account_id"]))

    async def _by_refresh(self, client: dict[str, Any], form: dict[str, str]) -> Reply:
        spent = await self._store.spend_refresh(form.get("refresh_token", ""))
        if spent is None or spent["client_id"] != client["client_id"]:
            return _oauth_error("invalid_grant", "The refresh token is not valid.")
        return _json(200, await self._store.issue_tokens(client["client_id"], spent["account_id"]))

    async def _revoke(self, body: str) -> Reply:
        await self._store.revoke(dict(parse_qsl(body)).get("token", ""))
        return Reply(200, "", None)

    async def _mcp(self, body: str, headers: dict[str, str]) -> Reply:
        token = await self._store.live_token(
            headers.get("authorization", "").removeprefix("Bearer "), "access"
        )
        if token is None:
            return _json(401, {"error": "invalid_token"}, {"www-authenticate": "Bearer"})
        try:
            message = json.loads(body)
            method, ident = message["method"], message.get("id")
        except ValueError, KeyError, TypeError:
            return _json(
                400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            )
        if ident is None:
            return Reply(202, "", None)
        account = await self._store.account(token["account_id"]) if token["account_id"] else None
        result, fate = await self._dispatch(
            method, message.get("params") or {}, SimContext(self._store, self._clock, account)
        )
        if fate == "drop":
            return Reply(502, "Bad gateway", "text/plain")
        return await self._answer(ident, result)

    async def _dispatch(
        self, method: str, params: dict[str, Any], ctx: SimContext
    ) -> tuple[dict[str, Any], str]:
        match method:
            case "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER,
                }
                return result, "ok"
            case "tools/list":
                return {
                    "tools": [{**tool, "description": f"{tool['name']} (simulated)"} for tool in TOOLS]
                }, "ok"
            case "tools/call":
                return await self._call(ctx, params)
            case _:
                return {"error": {"code": -32601, "message": f"Method not found: {method}"}}, "ok"

    async def _call(self, ctx: SimContext, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
        name = str(params.get("name"))
        if ctx.account is None and name not in PUBLIC_TOOLS:
            answered = {
                "content": [{"type": "text", "text": "This needs a person's own Index account."}],
                "isError": True,
            }
            return answered, "ok"
        answer = await run(ctx, name, params.get("arguments") or {})
        result: dict[str, Any] = {"content": [{"type": "text", "text": answer.text}], "isError": answer.error}
        if answer.data:
            result["structuredContent"] = answer.data
        return result, answer.fate

    async def _answer(self, ident: Any, result: dict[str, Any]) -> Reply:
        body = {
            "jsonrpc": "2.0",
            "id": ident,
            **({"error": result["error"]} if "error" in result else {"result": result}),
        }
        headers = {SESSION_HEADER: "sim-session"} if "protocolVersion" in result else {}
        if await self._store.setting(SSE_SETTING, "") == "1":
            return Reply(200, f"event: message\ndata: {json.dumps(body)}\n\n", "text/event-stream", headers)
        return _json(200, body, headers)
