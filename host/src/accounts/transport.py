# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fetching Google's key document: one GET that answers (status, headers, body)."""

import httpx

from config import runtime

from .keys import KeysUnavailable

TIMEOUT_SECONDS = 8


def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    """Inside a Worker the request is made with the async client and waited for (as the connectors' are);
    elsewhere with the plain one."""
    try:
        if runtime.IS_WORKER:
            from pyodide.ffi import run_sync

            async def get() -> httpx.Response:
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                    return await client.get(url)

            response = run_sync(get())
        else:
            response = httpx.get(url, timeout=TIMEOUT_SECONDS)
    except httpx.HTTPError as error:
        raise KeysUnavailable("Google's keys could not be reached.") from error
    return response.status_code, dict(response.headers), response.content
