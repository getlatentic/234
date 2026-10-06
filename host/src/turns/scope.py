# SPDX-License-Identifier: AGPL-3.0-or-later
"""The connectors a chat may use (chat_chat.connectors, set for a Brand's chats in pact/brands.py): the model
is shown their tools only, and a call to any other connector's tool is refused, whatever the model asks
for."""

from typing import Any

from .hub import SEPARATOR

OUTSIDE = "This tool is not offered in this conversation."


def servers_of(column: str | None) -> tuple[str, ...]:
    """Empty means every connector."""
    return tuple(name for name in (column or "").split(",") if name)


def allows(qualified: str, servers: tuple[str, ...]) -> bool:
    return not servers or qualified.partition(SEPARATOR)[0] in servers


def within(tools: list[dict[str, Any]], servers: tuple[str, ...]) -> list[dict[str, Any]]:
    return [tool for tool in tools if allows(tool["function"]["name"], servers)]
