# SPDX-License-Identifier: AGPL-3.0-or-later
"""How a page is fetched: one GET that does not follow a redirect and reads at most `max_bytes`. The Workers
runtime implements it; the tests script it."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


class FetchFailed(Exception):
    """Nothing usable came back: no connection, a timeout."""


@dataclass(frozen=True)
class Fetched:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    too_large: bool = False


class Fetcher(Protocol):
    async def get(
        self, url: str, *, headers: Mapping[str, str], timeout_seconds: float, max_bytes: int
    ) -> Fetched: ...


class WorkerPageFetch:
    """The Workers runtime's `fetch`, read as a stream so a large page is cut off, not downloaded."""

    async def get(
        self, url: str, *, headers: Mapping[str, str], timeout_seconds: float, max_bytes: int
    ) -> Fetched:
        from js import AbortSignal, Object, fetch
        from pyodide.ffi import to_js

        init: dict[str, Any] = {
            "method": "GET",
            "headers": dict(headers),
            "redirect": "manual",
            "signal": AbortSignal.timeout(int(timeout_seconds * 1000)),
        }
        try:
            response = await fetch(url, to_js(init, dict_converter=Object.fromEntries))
            body, too_large = await self._read(response, max_bytes)
        except Exception as error:
            raise FetchFailed(str(error)) from error
        seen = {name: str(response.headers.get(name) or "") for name in ("content-type", "location")}
        return Fetched(int(response.status), seen, body, too_large)

    @staticmethod
    async def _read(response: Any, max_bytes: int) -> tuple[bytes, bool]:
        if response.body is None:
            return b"", False
        reader, chunks, size = response.body.getReader(), [], 0
        while True:
            step = await reader.read()
            if step.done:
                return b"".join(chunks), False
            chunk = bytes(step.value.to_py())
            size += len(chunk)
            if size > max_bytes:
                await reader.cancel()
                return b"", True
            chunks.append(chunk)
