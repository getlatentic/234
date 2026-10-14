# SPDX-License-Identifier: AGPL-3.0-or-later
"""Talking MCP to Paystack Index (Streamable HTTP, protocol 2025-03-26): one JSON-RPC request in a POST, the
answer as JSON or as a server-sent event. A session is opened on the first call (`initialize`, then the
`initialized` notification) and carries the server's session id if it gave one. Index's words are returned as
they came; whoever shows one to a person or a model cleans it first (commerce/text.py).

What each failure means to a caller that may be charging someone: `IndexUnauthorized` (HTTP 401) and
`IndexRefused` (another 4xx, a JSON-RPC error) mean Index did not act; `IndexUnreachable` (no answer, a 5xx)
means it may have."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ...transport import Reply, Transport, TransportError

PROTOCOL_VERSION = "2025-03-26"
USER_AGENT = "234/1.0 (+https://234.getlatentic.com; Paystack Index connector)"
TIMEOUT_SECONDS = 25.0
MAX_BODY = 1_000_000
SESSION_HEADER = "mcp-session-id"


class IndexProblem(Exception):
    """Anything Index's side did not do as asked."""


class IndexUnreachable(IndexProblem):
    """No usable answer: the request may or may not have been acted on."""


class IndexUnauthorized(IndexProblem):
    """Index did not accept the token. It did not act."""


class IndexRefused(IndexProblem):
    """Index answered that it would not do it. It did not act."""


class IndexMisread(IndexProblem):
    """Index answered in a shape 234 does not read. Whether it acted is for the caller to say."""


@dataclass(frozen=True)
class ToolReply:
    text: str
    data: dict[str, Any]
    is_error: bool


def sse_messages(body: str) -> list[dict[str, Any]]:
    """The JSON messages of a server-sent event stream, in order."""
    found, chunk = [], []
    for line in [*body.splitlines(), ""]:
        if line.startswith("data:"):
            chunk.append(line[5:].strip())
        elif not line and chunk:
            try:
                parsed = json.loads("".join(chunk))
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                found.append(parsed)
            chunk = []
    return found


def message_of(reply: Reply, request_id: int | None) -> dict[str, Any] | None:
    """The JSON-RPC message that answers `request_id`; None for a notification's empty acknowledgement."""
    if len(reply.body) > MAX_BODY:
        raise IndexMisread("Index's answer was too large to read.")
    if not reply.body.strip():
        return None
    streamed = "event-stream" in (reply.content_type or "")
    try:
        messages = sse_messages(reply.body) if streamed else [json.loads(reply.body)]
    except ValueError as error:
        raise IndexMisread("Index did not answer in JSON.") from error
    answers = [
        m for m in messages if isinstance(m, dict) and (request_id is None or m.get("id") == request_id)
    ]
    return answers[-1] if answers else None


def reply_of(result: Mapping[str, Any]) -> ToolReply:
    """A tool result as text, structured data (or the JSON in its text), and whether Index called it an
    error."""
    blocks = result.get("content") if isinstance(result.get("content"), list) else []
    text = "\n".join(
        str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text"
    )
    data = result.get("structuredContent")
    if not isinstance(data, dict):
        try:
            data = json.loads(text) if text.lstrip().startswith("{") else {}
        except ValueError:
            data = {}
    return ToolReply(text, data if isinstance(data, dict) else {}, bool(result.get("isError")))


@dataclass
class IndexSession:
    transport: Transport
    url: str
    token: str
    _next_id: int = field(default=1, init=False)
    _session_id: str | None = field(default=None, init=False)
    _opened: bool = field(default=False, init=False)

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "authorization": f"Bearer {self.token}",
            "user-agent": USER_AGENT,
        }
        if self._session_id:
            headers[SESSION_HEADER] = self._session_id
        return headers

    async def _post(self, message: dict[str, Any]) -> Reply:
        try:
            reply = await self.transport.send(
                "POST",
                self.url,
                headers=self._headers(),
                body=json.dumps(message),
                timeout_seconds=TIMEOUT_SECONDS,
            )
        except TransportError as error:
            raise IndexUnreachable(str(error)) from error
        if reply.status == 401:
            raise IndexUnauthorized("Index did not accept the token.")
        if reply.status >= 500:
            raise IndexUnreachable(f"Index answered {reply.status}.")
        if not reply.ok:
            raise IndexRefused(f"Index answered {reply.status}.")
        return reply

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id, self._next_id = self._next_id, self._next_id + 1
        reply = await self._post({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        self._session_id = reply.headers.get(SESSION_HEADER) or self._session_id
        answer = message_of(reply, request_id)
        if answer is None:
            raise IndexMisread("Index did not answer.")
        if isinstance(answer.get("error"), dict):
            raise IndexRefused(str(answer["error"].get("message", "Index refused the request.")))
        result = answer.get("result")
        if not isinstance(result, dict):
            raise IndexMisread("Index's answer had no result.")
        return result

    async def _open(self) -> None:
        if self._opened:
            return
        await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "234", "version": "1.0"},
            },
        )
        await self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._opened = True

    async def call(self, name: str, arguments: Mapping[str, Any]) -> ToolReply:
        await self._open()
        result = await self._request("tools/call", {"name": name, "arguments": dict(arguments)})
        return reply_of(result)


SessionFactory = Callable[[str], IndexSession]
"""A session on Index for a token."""
