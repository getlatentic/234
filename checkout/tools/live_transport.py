# SPDX-License-Identifier: AGPL-3.0-or-later
"""A plain HTTPS client for a script run on a laptop; the Worker uses its own fetch."""

import asyncio
import urllib.error
import urllib.request
from collections.abc import Mapping

from checkout.transport import Reply, TransportError


class UrllibTransport:
    """A plain HTTPS client for a script run on a laptop; the Worker uses its own fetch."""

    async def send(
        self, method: str, url: str, *, headers: Mapping[str, str], body: str | None, timeout_seconds: float
    ) -> Reply:
        return await asyncio.to_thread(self._send, method, url, dict(headers), body, timeout_seconds)

    @staticmethod
    def _send(method: str, url: str, headers: dict[str, str], body: str | None, timeout: float) -> Reply:
        request = urllib.request.Request(
            url, data=None if body is None else body.encode(), headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return Reply(response.status, response.read().decode(), response.headers.get("content-type"))
        except urllib.error.HTTPError as error:
            return Reply(error.code, error.read().decode(), error.headers.get("content-type"))
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise TransportError(str(error)) from error
