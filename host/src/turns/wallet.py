# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wallet in a turn: only a signed-in account has one (docs/wallet.md). For anyone else the wallet tool is
not offered, and a call to a wallet tool, from the model or from a card, is refused before it leaves the
host. The connector refuses a call without the account header as well."""

from typing import Any

from .hub import SEPARATOR, WALLET_SERVER

WALLET_TOOLS = f"{WALLET_SERVER}{SEPARATOR}"
NOT_AN_ACCOUNT = "A wallet is for signed-in accounts."


def is_wallet_tool(qualified: str) -> bool:
    return qualified.startswith(WALLET_TOOLS)


def kept(tools: list[dict[str, Any]], account: bool) -> list[dict[str, Any]]:
    """The tools, without the wallet's unless the chat belongs to an account."""
    return [tool for tool in tools if account or not is_wallet_tool(tool["function"]["name"])]
