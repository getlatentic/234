# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cloudflare Turnstile before a visitor's first message (docs/bot-check.md). The page asks Turnstile for a
token when the first message is sent; this asks Cloudflare whether the token is good. Three answers:

- `PASSED`: Cloudflare says the token is a person's, made for this action on one of this host's own
  addresses, and not used before.
- `REFUSED`: no token, or Cloudflare says it is not good.
- `UNAVAILABLE`: Cloudflare could not be asked (it did not answer, or answered with a fault). A chat is then
  let through, and the limits that were always there (the message rate, the daily model calls and money) hold.
  A check that fails shut would stop every first message whenever Cloudflare has a bad minute.
"""

import json
import logging
from urllib.parse import urlencode

import httpx
from django.conf import settings

from config import runtime

log = logging.getLogger(__name__)

SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_SECONDS = 5
MAX_TOKEN = 2048
ACTION = "start"
PASSED, REFUSED, UNAVAILABLE = "passed", "refused", "unavailable"
TEST_KEYS = ("1x00000000000000000000", "2x00000000000000000000", "3x00000000000000000000")
"""Cloudflare's published test site keys, whose tokens carry no action and a hostname of example.com."""


def ask(form: str) -> tuple[int, bytes]:
    """One POST to Cloudflare's siteverify: status and body. Inside a Worker the async client is waited for
    (as the connectors' calls are); elsewhere the plain one."""
    headers = {"content-type": "application/x-www-form-urlencoded"}
    if runtime.IS_WORKER:
        from pyodide.ffi import run_sync

        async def post() -> httpx.Response:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                return await client.post(SITEVERIFY, content=form, headers=headers)

        response = run_sync(post())
    else:
        response = httpx.post(SITEVERIFY, content=form, headers=headers, timeout=TIMEOUT_SECONDS)
    return response.status_code, response.content


def _for_this_host(answer: dict) -> bool:
    """The token was made for the action the page asks for, on an address of this host. Cloudflare's test keys
    return neither, so a stack that uses them is not held to it."""
    if settings.TURNSTILE_SITE_KEY.startswith(TEST_KEYS):
        return True
    hosts = settings.TURNSTILE_HOSTNAMES or settings.ALLOWED_HOSTS
    return answer.get("action") == ACTION and answer.get("hostname") in hosts


def verdict(token: object, remote_ip: str = "") -> str:
    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN:
        return REFUSED
    form = {"secret": settings.TURNSTILE_SECRET, "response": token}
    if remote_ip:
        form["remoteip"] = remote_ip
    try:
        status, body = ask(urlencode(form))
        answer = json.loads(body)
    except httpx.HTTPError, ValueError:
        log.warning("Turnstile could not be asked; the chat is let through", exc_info=True)
        return UNAVAILABLE
    if status >= 500 or not isinstance(answer, dict):
        log.warning("Turnstile answered %s; the chat is let through", status)
        return UNAVAILABLE
    return PASSED if answer.get("success") is True and _for_this_host(answer) else REFUSED
