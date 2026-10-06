# SPDX-License-Identifier: AGPL-3.0-or-later
"""Short-lived signed values that let one request act for another: a WebSocket ticket and a share link.
Both are HMACs (Django's signing) with a salt of their own."""

from typing import Any

from django.core import signing

WS_SALT = "chat.ws"
SHARE_SALT = "chat.share"
WS_TTL_SECONDS = 60
SHARE_TTL_SECONDS = 3600


def _mint(salt: str, value: dict[str, Any]) -> str:
    return signing.dumps(value, salt=salt, compress=False)


def _open(salt: str, token: str, max_age: int) -> dict[str, Any] | None:
    try:
        value = signing.loads(token, salt=salt, max_age=max_age)
    except signing.BadSignature:
        return None
    return value if isinstance(value, dict) else None


def mint_ws_ticket(chat_id: str) -> str:
    return _mint(WS_SALT, {"chat": chat_id})


def chat_for_ws_ticket(token: str) -> str | None:
    value = _open(WS_SALT, token, WS_TTL_SECONDS)
    return value["chat"] if value else None


def mint_share_token(chat_id: str) -> str:
    return _mint(SHARE_SALT, {"chat": chat_id})


def chat_for_share_token(token: str) -> str | None:
    value = _open(SHARE_SALT, token, SHARE_TTL_SECONDS)
    return value["chat"] if value else None
