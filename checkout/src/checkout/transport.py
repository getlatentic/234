# SPDX-License-Identifier: AGPL-3.0-or-later
"""How the provider clients reach a provider: one call, one reply, or `TransportError` when nothing
usable came back (no connection, a timeout). The simulators implement the same seam, so the real
clients run unchanged in simulated mode, and the tests script it."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class TransportError(Exception):
    """No reply arrived: the request may or may not have reached the provider."""


@dataclass(frozen=True)
class Reply:
    status: int
    body: str
    content_type: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Transport(Protocol):
    async def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: str | None,
        timeout_seconds: float,
    ) -> Reply: ...


class WorkerFetch:
    """The Workers runtime's `fetch`. It is imported when used so the package loads anywhere. With
    `follow_redirects=False` a redirect comes back as the reply instead of being followed."""

    def __init__(self, *, follow_redirects: bool = True) -> None:
        self._follow = follow_redirects

    async def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: str | None,
        timeout_seconds: float,
    ) -> Reply:
        from js import AbortSignal, Object, fetch
        from pyodide.ffi import to_js

        init: dict[str, Any] = {
            "method": method,
            "headers": dict(headers),
            "signal": AbortSignal.timeout(int(timeout_seconds * 1000)),
        }
        if not self._follow:
            init["redirect"] = "manual"
        if body is not None:
            init["body"] = body
        try:
            response = await fetch(url, to_js(init, dict_converter=Object.fromEntries))
            text = await response.text()
        except Exception as error:
            raise TransportError(str(error)) from error
        kind = response.headers.get("content-type")
        return Reply(int(response.status), str(text), kind if isinstance(kind, str) else None)


class BindingFetch:
    """Requests sent through a Workers service binding to another Worker of the same account. Only the
    path and query of the URL route the request; its host is never contacted."""

    def __init__(self, binding: Any) -> None:
        self._binding = binding

    async def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: str | None,
        timeout_seconds: float,
    ) -> Reply:
        del timeout_seconds
        try:
            reply = await self._binding.fetch(url, method=method, headers=dict(headers), body=body)
            text = await reply.text()
        except Exception as error:
            raise TransportError(str(error)) from error
        kind = reply.headers.get("content-type")
        return Reply(int(reply.status), str(text), kind if isinstance(kind, str) else None)
