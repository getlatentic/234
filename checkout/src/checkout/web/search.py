# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web search through Amazon Bedrock AgentCore's managed Web Search tool (docs/web.md): an AgentCore Gateway
in the owner's AWS account, with the `web-search` connector as its target, speaks MCP over HTTPS and takes IAM
(SigV4) credentials. 234 calls it from outside AWS with a key that may invoke that gateway and nothing else.

The gateway's tool is `<target>___WebSearch`, taking `query` (200 characters at most) and `maxResults` (1 to
25), and giving `results` of `text` (a snippet), `url`, `title` and `publishedDate`."""

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from ..errors import DomainError
from ..transport import Reply, Transport, TransportError
from . import safe_url
from .sigv4 import Credentials, signed_headers

SERVICE = "bedrock-agentcore"
PROTOCOL = "2025-06-18"
QUERY_CHARS = 200
SNIPPET_CHARS = 500
MAX_RESULTS = 10
TIMEOUT_SECONDS = 15
UNAVAILABLE = "SEARCH_UNAVAILABLE: Web search did not answer. Say so, and do not answer from memory."


@dataclass(frozen=True)
class Hit:
    title: str
    url: str
    snippet: str
    published: str | None


def gateway_problem(url: str, region: str) -> str | None:
    """Why this is not an AgentCore Gateway's address in `region`, or None."""
    parts = urlsplit(url)
    suffix = f".gateway.bedrock-agentcore.{region}.amazonaws.com"
    if (
        parts.scheme != "https"
        or not (parts.hostname or "").endswith(suffix)
        or parts.port not in (None, 443)
    ):
        return f"The search gateway is an https address ending {suffix}."
    return None


def _json_of(reply: Reply) -> dict[str, Any]:
    """The JSON-RPC message in a reply, which Streamable HTTP sends as JSON or as one server-sent event."""
    text = reply.body.strip()
    if "event-stream" in (reply.content_type or ""):
        datas = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        text = next((d for d in reversed(datas) if d), "")
    try:
        message = json.loads(text)
    except ValueError as error:
        raise DomainError("SEARCH_UNAVAILABLE", UNAVAILABLE) from error
    return message if isinstance(message, dict) else {}


def hits_of(result: dict[str, Any]) -> list[Hit]:
    """The results a WebSearch call gave: in `structuredContent`, or as JSON in the first content block."""
    data = result.get("structuredContent")
    if not isinstance(data, dict):
        blocks = result.get("content") or [{}]
        try:
            data = json.loads(blocks[0].get("text", ""))
        except ValueError, AttributeError:
            data = {}
    found = []
    for item in (data.get("results") if isinstance(data, dict) else None) or []:
        url = str(item.get("url", ""))
        if safe_url.problem(url) is None:
            published = item.get("publishedDate")
            found.append(
                Hit(
                    str(item.get("title") or url)[:200],
                    url,
                    str(item.get("text", ""))[:SNIPPET_CHARS],
                    str(published) if published else None,
                )
            )
    return found[:MAX_RESULTS]


class GatewaySearch:
    def __init__(
        self, transport: Transport, credentials: Credentials, url: str, target: str, region: str, clock
    ) -> None:
        self._transport, self._credentials, self._url = transport, credentials, url
        self._target, self._region, self._clock = target, region, clock
        self._ready = False
        self._ids = 0

    async def search(self, query: str, limit: int) -> list[Hit]:
        arguments = {"query": query[:QUERY_CHARS], "maxResults": max(1, min(limit, MAX_RESULTS))}
        try:
            if not self._ready:
                await self._handshake()
            message = await self._rpc(
                "tools/call", {"name": f"{self._target}___WebSearch", "arguments": arguments}
            )
        except DomainError:
            self._ready = False
            raise
        result = message.get("result")
        if not isinstance(result, dict) or result.get("isError"):
            raise DomainError("SEARCH_UNAVAILABLE", UNAVAILABLE)
        return hits_of(result)

    async def _handshake(self) -> None:
        params = {
            "protocolVersion": PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "234", "version": "1"},
        }
        if "error" in await self._rpc("initialize", params):
            raise DomainError("SEARCH_UNAVAILABLE", UNAVAILABLE)
        await self._rpc("notifications/initialized", None, notification=True)
        self._ready = True

    async def _rpc(
        self, method: str, params: dict[str, Any] | None, notification: bool = False
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notification:
            self._ids += 1
            body["id"] = self._ids
        raw = json.dumps(body).encode()
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": PROTOCOL,
        }
        signed = signed_headers(
            self._credentials, "POST", self._url, raw, self._region, SERVICE, self._clock(), headers
        )
        try:
            reply = await self._transport.send(
                "POST",
                self._url,
                headers={k: v for k, v in signed.items() if k != "host"},
                body=raw.decode(),
                timeout_seconds=TIMEOUT_SECONDS,
            )
        except TransportError as error:
            raise DomainError("SEARCH_UNAVAILABLE", UNAVAILABLE) from error
        if not reply.ok:
            raise DomainError("SEARCH_UNAVAILABLE", UNAVAILABLE)
        return {} if notification else _json_of(reply)
