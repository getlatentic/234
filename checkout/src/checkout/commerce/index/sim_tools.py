# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated Index's tools. It advertises all ten of Index's tools and checks a call's arguments against
their schemas. The eight that 234 uses are implemented (`get_balance`, `browse_merchants`, `find_items`,
`order`, `quick_buy`, `connect_merchant`, `track_order`, `get_recent_activity`); the two transfer tools answer
that the simulator does not offer them."""

from datetime import UTC, datetime
from typing import Any

from . import sim_bills, sim_chowdeck
from .sim_catalog import merchants
from .sim_schema import problem
from .sim_tool_list import TOOLS
from .sim_tools_base import SimContext, ToolAnswer, refusal, success

SCHEMAS = {tool["name"]: tool["inputSchema"] for tool in TOOLS}
NOT_SIMULATED = "The simulated Index does not offer {name}."


async def get_balance(ctx: SimContext, args: dict[str, Any]) -> ToolAnswer:
    account = ctx.account
    if account is None:
        return refusal("This needs a person's own Index account.")
    return success(
        "Balances",
        {
            "balance_kobo": 0,
            "zap_linked": account.zap_linked,
            "zap_balance_kobo": account.zap_kobo if account.zap_linked else None,
        },
    )


async def browse(ctx: SimContext, args: dict[str, Any]) -> ToolAnswer:
    linked = ctx.account is not None and ctx.account.chowdeck_linked
    listed = []
    for entry in merchants():
        if args.get("category") not in (None, entry["category"]):
            continue
        if args.get("include_coming_soon") is False and entry["status"] == "coming_soon":
            continue
        listed.append(
            {**entry, "requires_link": entry["requires_link"] and not (entry["id"] == "chowdeck" and linked)}
        )
    return success("Merchants", {"merchants": listed})


def _iso(at_ms: int) -> str:
    return datetime.fromtimestamp(at_ms / 1000, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


async def activity(ctx: SimContext, args: dict[str, Any]) -> ToolAnswer:
    if ctx.account is None:
        return refusal("This needs a person's own Index account.")
    if args.get("source") != "zap":
        return success("Index credits activity", {"transactions": []})
    spent = [
        {"id": o["id"], "type": "debit", "amount_kobo": o["total_kobo"], "created_at": _iso(o["created_at"])}
        for o in await ctx.store.orders(ctx.account.id)
    ]
    return success("Zap activity", {"transactions": spent, "totals_partial": False})


HANDLERS = {
    "get_balance": get_balance,
    "browse_merchants": browse,
    "get_recent_activity": activity,
    "find_items": sim_chowdeck.find_items,
    "order": sim_chowdeck.order,
    "track_order": sim_chowdeck.track,
    "connect_merchant": sim_chowdeck.connect,
    "quick_buy": sim_bills.quick_buy,
}


async def run(ctx: SimContext, name: str, arguments: dict[str, Any]) -> ToolAnswer:
    """The tool's answer, or the refusal Index gives for a name it does not have or arguments that break its
    schema. Every call is recorded first, as served."""
    if name not in SCHEMAS:
        return refusal(f"Unknown tool: {name}")
    await ctx.store.record_call(ctx.account.id if ctx.account else None, name, arguments)
    if (why := problem(arguments, SCHEMAS[name])) is not None:
        return refusal(f"Invalid arguments: {why}")
    handler = HANDLERS.get(name)
    return await handler(ctx, arguments) if handler else refusal(NOT_SIMULATED.format(name=name))
