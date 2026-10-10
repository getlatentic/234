# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the scripted model does about the wallet, the way a model that follows the tool's description would:
"my wallet" or "wallet balance" shows the wallet card when the wallet tool is offered (an account), and says
it cannot otherwise; the balance the card shows is read back in one line. Used by fake_model.py."""

import re
from typing import Any

BALANCE = "wallet__wallet_balance"
ASK = re.compile(r"^(?:my wallet|wallet balance)$", re.I)
HOLDS = "The wallet holds "


def _content(message: dict[str, Any]) -> str:
    return message["content"] if isinstance(message.get("content"), str) else ""


def answer(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any] | None:
    last = messages[-1]
    content = _content(last)
    if last["role"] == "tool" and content.startswith(HOLDS):
        return {"text": f"Your wallet holds {content.removeprefix(HOLDS)}"}
    if last["role"] != "user" or not ASK.match(content.strip()):
        return None
    if any(t["function"]["name"] == BALANCE for t in tools):
        return {"tool": BALANCE, "arguments": {}}
    return {"text": "A wallet is for signed-in accounts: sign in to have one."}
