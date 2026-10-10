# SPDX-License-Identifier: AGPL-3.0-or-later
"""Doubles for memory in a turn: a hub that offers the memory tools beside the others, answers the memory
index from a value a test changes, and records which calls reached it and for whom."""

from typing import Any

from turns.hub import MEMORY_SERVER, HubError, ToolOutcome
from turns.ledger_owner import ledger_owner

ACCOUNT_HEX = "ab" * 16
ACCOUNT = f"u:{ACCOUNT_HEX}"
VISITOR = "v:" + "cd" * 16
AGENT = "a:partner"
INDEX = (
    "## Recipients\n- [Mum](0123456789abcdef) — Guaranty Trust Bank, SIMULATED ACCOUNT 6789, ends 6789\n"
    "## Facts\n- [Lives in](fedcba9876543210) — Yaba, Lagos"
)
TRANSFER = "send-money__create_transfer_quote"
MODEL_TOOLS = (
    "airtime__create_airtime_quote",
    TRANSFER,
    "memory__recall",
    "memory__remember",
    "memory__update",
    "memory__forget",
)


def transfer_tool() -> dict[str, Any]:
    """The transfer tool as the host's model schema leaves it: account and bank required of the model."""
    schema = {
        "type": "object",
        "properties": {
            "account_number": {"type": "string"},
            "bank": {"type": "string"},
            "recipient_memory_id": {"type": "string"},
            "amount_kobo": {"type": "integer"},
            "amount_as_user_said": {"type": "string"},
        },
        "required": ["amount_kobo", "amount_as_user_said", "account_number", "bank"],
    }
    return {"type": "function", "function": {"name": TRANSFER, "description": "t", "parameters": schema}}


class MemoryHub:
    """The connectors with memory: `index` is what the memory index answers now, and `owners` and `calls` say
    who each memory call was for."""

    def __init__(self, index: str = INDEX, results: dict[str, Any] | None = None) -> None:
        self.index = index
        self.results = results or {}
        self.index_fails: Exception | None = None
        self.calls: list[tuple[str, str, dict]] = []
        self.owners: list[str] = []
        self.model_calls: list[tuple[str, dict]] = []

    async def model_tools(self) -> list[dict[str, Any]]:
        tools = [
            {"type": "function", "function": {"name": name, "description": "t", "parameters": {}}}
            for name in MODEL_TOOLS
            if name != TRANSFER
        ]
        return [*tools, transfer_tool()]

    async def keyed(self, qualified: str) -> bool:
        return False

    async def call_model_tool(
        self, qualified: str, arguments: dict, owner: str, key: str, account: bool = False
    ) -> ToolOutcome:
        self.model_calls.append((qualified, arguments))
        self.owners.append(owner)
        server, _, tool = qualified.partition("__")
        return ToolOutcome(server, tool, self.results[qualified], None)

    async def call_app_tool(
        self, server: str, name: str, arguments: dict, owner: str, account: bool = False
    ) -> dict[str, Any]:
        self.calls.append((server, name, arguments))
        self.owners.append(owner)
        if self.index_fails:
            raise self.index_fails
        if server != MEMORY_SERVER:
            raise HubError("not here")
        if name == "memory_index":
            return {
                "content": [{"type": "text", "text": self.index or "No notes."}],
                "structuredContent": {"index": self.index, "entries": 2, "tokens": 40},
            }
        return self.results[name]

    def index_calls(self) -> int:
        return sum(1 for _, name, _ in self.calls if name == "memory_index")


def key_of(owner: str) -> str:
    return ledger_owner(owner)
