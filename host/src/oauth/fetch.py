# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fetching a client ID metadata document: one GET, no redirect followed, at most 10 KB read."""

import httpx

from config import runtime

TIMEOUT_SECONDS = 5
HEADERS = {"accept": "application/json"}


def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    try:
        if runtime.IS_WORKER:
            from pyodide.ffi import run_sync

            async def get() -> httpx.Response:
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
                    return await client.get(url, headers=HEADERS)

            response = run_sync(get())
        else:
            response = httpx.get(url, timeout=TIMEOUT_SECONDS, follow_redirects=False, headers=HEADERS)
    except httpx.HTTPError:
        return 0, {}, b""
    return response.status_code, dict(response.headers), response.content
