# SPDX-License-Identifier: AGPL-3.0-or-later
"""`events/list`, `events/subscribe` and `events/unsubscribe` for one connector, acting for the owner of the
call. A new subscription is stored only after its callback has answered the challenge."""

from typing import Any

from ..clock import Clock
from ..transport import Transport
from . import callbacks, catalog
from .delivery import iso
from .signing import key_of
from .subscriptions import Request, Subscriptions, granted_ttl


class EventError(Exception):
    """A request the server refuses: `code` is the JSON-RPC error, `data` its details."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code, self.data = code, data


INVALID_PARAMS = -32602
CALLBACK_ENDPOINT_ERROR = -32015


def _delivery(params: dict[str, Any], need_secret: bool) -> tuple[str, str | None]:
    delivery = params.get("delivery")
    if not isinstance(delivery, dict) or delivery.get("mode") != "webhook":
        raise EventError(INVALID_PARAMS, 'delivery.mode must be "webhook"')
    secret = delivery.get("secret")
    if need_secret:
        try:
            key_of(secret)
        except ValueError as error:
            raise EventError(INVALID_PARAMS, f"delivery.secret: {error}") from error
    return delivery.get("url"), secret


class Events:
    def __init__(
        self, subscriptions: Subscriptions, transport: Transport, clock: Clock, allow_loopback: bool
    ):
        self._subscriptions, self._transport, self._clock = subscriptions, transport, clock
        self._allow_loopback = allow_loopback

    def list(self, connector: str) -> dict[str, Any]:
        return {"events": [catalog.definition(connector)], "nextCursor": None}

    def _request(self, owner: str, connector: str, params: dict[str, Any], need_secret: bool):
        if params.get("name") != catalog.QUOTE_FINISHED:
            raise EventError(INVALID_PARAMS, f"Unknown event: {params.get('name')}")
        arguments = params.get("arguments", {})
        try:
            quote_id = catalog.quote_filter(arguments)
        except ValueError as error:
            raise EventError(INVALID_PARAMS, f"arguments: {error}") from error
        url, secret = _delivery(params, need_secret)
        try:
            url = callbacks.check_url(url, self._allow_loopback)
        except callbacks.CallbackRefused as refused:
            raise EventError(CALLBACK_ENDPOINT_ERROR, str(refused), {"reason": refused.reason}) from refused
        return Request(owner, connector, catalog.QUOTE_FINISHED, arguments, url), quote_id, secret

    async def subscribe(self, owner: str, connector: str, params: dict[str, Any]) -> dict[str, Any]:
        asked, quote_id, secret = self._request(owner, connector, params, need_secret=True)
        try:
            ttl = granted_ttl(params.get("ttlMs"))
        except ValueError as error:
            raise EventError(INVALID_PARAMS, str(error)) from error
        now = self._clock.now()
        if not await self._subscriptions.exists(asked.id):
            try:
                await callbacks.verify(self._transport, asked.url, secret, asked.id, now // 1000)
            except callbacks.CallbackRefused as refused:
                raise EventError(
                    CALLBACK_ENDPOINT_ERROR, str(refused), {"reason": refused.reason}
                ) from refused
        await self._subscriptions.save(asked, quote_id, secret, now + ttl, now)
        return {"id": asked.id, "refreshBefore": iso(now + ttl), "cursor": None, "truncated": False}

    async def unsubscribe(self, owner: str, connector: str, params: dict[str, Any]) -> dict[str, Any]:
        asked, _, _ = self._request(owner, connector, params, need_secret=False)
        await self._subscriptions.remove(asked.id, owner)
        return {}
