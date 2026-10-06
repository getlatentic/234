# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fetching a personal agent's JWKS: one GET, no redirect followed."""

import httpx

from config import runtime

from .jwks import KeysUnavailable

TIMEOUT_SECONDS = 5


def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    try:
        if runtime.IS_WORKER:
            from pyodide.ffi import run_sync

            async def get() -> httpx.Response:
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
                    return await client.get(url)

            response = run_sync(get())
        else:
            response = httpx.get(url, timeout=TIMEOUT_SECONDS, follow_redirects=False)
    except httpx.HTTPError as error:
        raise KeysUnavailable("The JWKS could not be reached.") from error
    return response.status_code, dict(response.headers), response.content
