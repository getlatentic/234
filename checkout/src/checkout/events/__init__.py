# SPDX-License-Identifier: AGPL-3.0-or-later
"""MCP events for the connectors that move money: one connector's methods, acting for the owner of the
call (the owner header the chat host sets, the same as for tools)."""

from collections.abc import Callable
from typing import Any

from .service import EventError, Events

__all__ = ["ConnectorEvents", "EventError", "Events"]


class ConnectorEvents:
    def __init__(self, events: Events, connector: str, owner: Callable[[], str]) -> None:
        self._events, self._connector, self._owner = events, connector, owner

    async def answer(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "events/list":
            return self._events.list(self._connector)
        if method == "events/subscribe":
            return await self._events.subscribe(self._owner(), self._connector, params)
        return await self._events.unsubscribe(self._owner(), self._connector, params)
