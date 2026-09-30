# SPDX-License-Identifier: AGPL-3.0-or-later
"""An httpx transport that sends each request through a Workers service binding.

A Worker cannot fetch another Worker of the same account by its public workers.dev address (the request
never reaches it), so the host reaches the connectors through a binding. The URL's host is not used to
route; only the path and query are read by the connector.
"""

from collections.abc import Iterable
from typing import Any

import httpx

HOP_HEADERS = {"content-encoding", "content-length", "transfer-encoding", "connection"}


def response_headers(items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """The headers of a reply as it arrives decoded and whole: those describing the wire are dropped."""
    return [(name, value) for name, value in items if name.lower() not in HOP_HEADERS]


class ServiceBindingTransport(httpx.AsyncBaseTransport):
    def __init__(self, binding: Any) -> None:
        self._binding = binding

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        reply = await self._binding.fetch(
            str(request.url),
            method=request.method,
            headers=dict(request.headers),
            body=body.decode() if body else None,
        )
        return httpx.Response(
            reply.status,
            headers=response_headers(reply.headers.items()),
            content=await reply.bytes(),
            request=request,
        )


def connector_client(env: Any, binding_name: str, fallback: httpx.AsyncClient) -> httpx.AsyncClient:
    """The client for the connectors: through the named service binding when one is configured, else the
    ordinary client (local development reaches the connectors over localhost)."""
    if not binding_name:
        return fallback
    binding = getattr(env, binding_name, None)
    if binding is None:
        raise RuntimeError(f"The service binding {binding_name} is configured but not bound.")
    return httpx.AsyncClient(transport=ServiceBindingTransport(binding), timeout=30)
