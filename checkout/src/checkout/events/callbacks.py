# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where events may be sent, and the challenge a callback must answer before any event goes to it: HTTPS on
a host name (no address, no localhost; loopback HTTP only where test routes are on), no redirect followed."""

import hmac
import json
import secrets
from urllib.parse import urlsplit

from ..transport import Transport, TransportError
from .signing import headers

TIMEOUT_SECONDS = 5.0
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
MAX_URL = 2000


class CallbackRefused(Exception):
    """The callback cannot be used; `reason` is one of the spec's categories."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def check_url(url: object, allow_loopback: bool) -> str:
    if not isinstance(url, str) or len(url) > MAX_URL:
        raise CallbackRefused("invalid_url", "delivery.url must be a URL of at most 2000 characters")
    parts = urlsplit(url)
    host = parts.hostname or ""
    if allow_loopback and parts.scheme == "http" and host in LOOPBACK:
        return url
    is_address = host.replace(".", "").isdigit() or ":" in host
    if parts.scheme != "https" or not host or "." not in host or is_address or host in LOOPBACK:
        raise CallbackRefused("invalid_url", "delivery.url must be HTTPS on a public host name")
    if parts.username or parts.password or parts.fragment:
        raise CallbackRefused("invalid_url", "delivery.url may not carry user information or a fragment")
    return url


async def verify(transport: Transport, url: str, secret: str, subscription_id: str, now_s: int) -> None:
    challenge = secrets.token_urlsafe(24)
    body = json.dumps({"type": "verification", "challenge": challenge}, separators=(",", ":"))
    message_id = f"msg_verification_{secrets.token_hex(8)}"
    try:
        reply = await transport.send(
            "POST",
            url,
            headers=headers(secret, message_id, now_s, body, subscription_id),
            body=body,
            timeout_seconds=TIMEOUT_SECONDS,
        )
    except TransportError as error:
        raise CallbackRefused("timeout", "the callback did not answer") from error
    if not reply.ok:
        raise CallbackRefused("http_error", f"the callback answered {reply.status}")
    try:
        echoed = json.loads(reply.body).get("challenge")
    except ValueError, AttributeError:
        echoed = None
    if not isinstance(echoed, str) or not hmac.compare_digest(echoed, challenge):
        raise CallbackRefused("challenge_failed", "the callback did not echo the challenge")
