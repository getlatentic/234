# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the memory tests: calls to the memory connector as the host makes them, and a note saved the
way a person saves one (a proposal, then Save on its card)."""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from checkout.app import card_reader, memory_context
from checkout.connectors import memory as memory_connector
from checkout.owner import MEMORY_OWNER_HEADER
from checkout.paystack.api import AccountLookup
from tests.connector_support import text_of
from tests.support import PaystackOverride, Stack

MUM = {"kind": "recipient", "title": "Mum", "account_number": "0123456789", "bank": "GTB"}
USUAL = {
    "kind": "preference",
    "title": "Usual airtime",
    "hook": "MTN, 500 naira",
    "body": "Buys MTN airtime of 500 naira.",
}
CITY = {"kind": "fact", "title": "Lives in", "hook": "Yaba, Lagos", "body": "Lives in Yaba, Lagos."}


async def memory_call(stack: Stack, owner: str, tool: str, /, **arguments: Any) -> dict[str, Any]:
    answer = await stack.mcp(
        "memory",
        "tools/call",
        {"name": tool, "arguments": arguments},
        owner,
        headers={MEMORY_OWNER_HEADER: owner},
    )
    return answer["result"]


def ok(result: dict[str, Any]) -> dict[str, Any]:
    assert "isError" not in result, text_of(result)
    return result


async def propose(stack: Stack, owner: str, tool: str = "remember", /, **arguments: Any) -> dict[str, Any]:
    return ok(await memory_call(stack, owner, tool, **arguments))


async def decide(
    stack: Stack, owner: str, proposed: dict[str, Any], tool: str = "confirm_memory"
) -> dict[str, Any]:
    return await memory_call(
        stack,
        owner,
        tool,
        proposal_id=proposed["structuredContent"]["proposal_id"],
        confirm_token=proposed["_meta"]["confirmToken"],
    )


async def saved(stack: Stack, owner: str, **fields: Any) -> str:
    """Saves a note as a person does and returns its id."""
    proposed = await propose(stack, owner, "remember", **fields)
    done = ok(await decide(stack, owner, proposed))
    assert done["structuredContent"]["memory"]["state"] == "saved"
    return proposed["structuredContent"]["proposal_id"]


async def entry_count(stack: Stack, owner: str | None = None) -> int:
    if owner is None:
        return await stack.count("memory_entry")
    row = await stack.db.row("SELECT COUNT(*) AS n FROM memory_entry WHERE owner = ?", owner)
    return row["n"]


def memory_of(stack: Stack):
    """The memory context the connector runs on, for a test that reaches the store or proposals directly."""
    contexts = stack.app.contexts
    return memory_context(stack.app.settings, contexts, stack.db, stack.clock, contexts["send-money"].audit)


async def answered(value: str) -> str:
    return value


def bank_answers(stack: Stack, resolve: Callable[[AccountLookup], Awaitable[str]]) -> PaystackOverride:
    """Memory asks the bank through the send-money Paystack client; this one answers from `resolve`."""
    contexts = stack.app.contexts
    memory = memory_context(stack.app.settings, contexts, stack.db, stack.clock, contexts["send-money"].audit)
    patched = PaystackOverride(memory.paystack, resolve_account=resolve)
    connector = memory_connector.build_connector(
        replace(memory, paystack=patched), card_reader("memory.html")
    )
    object.__setattr__(stack.app, "connectors", {**stack.app.connectors, "memory": connector})
    return patched
