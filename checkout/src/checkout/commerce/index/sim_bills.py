# SPDX-License-Identifier: AGPL-3.0-or-later
"""`quick_buy` of the simulated Index, as its description says: airtime in one call (₦50 to ₦5,000), electricity
in two (₦1,000 to ₦1,000,000; the first validates the meter and moves nothing, the second, with `confirmed`,
charges and returns a token for a prepaid meter), data as a catalog of bundles."""

from typing import Any

from ...money import format_naira
from .sim_catalog import DISCOS, METERS, TOKEN
from .sim_tools_base import SimContext, ToolAnswer, refusal, success

NAIRA = 100
BOUNDS = {"airtime": (50, 5_000), "electricity": (1_000, 1_000_000)}
BUNDLES = [
    {"bundle_code": "daily-1gb", "name": "1GB, 1 day", "price_kobo": 30_000},
    {"bundle_code": "monthly-10gb", "name": "10GB, 30 days", "price_kobo": 300_000},
]


def _amount(args: dict[str, Any]) -> tuple[int, ToolAnswer | None]:
    least, most = BOUNDS[args["category"]]
    naira = args.get("amount_naira")
    if not isinstance(naira, int | float) or not least <= naira <= most:
        return 0, refusal(f"The amount must be between ₦{least:,} and ₦{most:,}.")
    return round(naira * NAIRA), None


async def _airtime(ctx: SimContext, args: dict[str, Any], total: int) -> ToolAnswer:
    if not args.get("network") or not args.get("phone"):
        return refusal("Airtime needs a network and a phone number.")
    return await ctx.charge("quick_buy", args, total, {"network": args["network"], "phone": args["phone"]})


async def _electricity(ctx: SimContext, args: dict[str, Any], total: int) -> ToolAnswer:
    if args.get("disco") not in DISCOS or args.get("meter_type") not in ("prepaid", "postpaid"):
        return refusal("Electricity needs a distribution company and a meter type.")
    holder = METERS.get(str(args.get("meter_number")))
    if holder is None:
        return refusal(f"{DISCOS[args['disco']]} could not find that meter number.")
    assert ctx.account is not None
    if args.get("confirmed") is not True:
        after = ctx.account.zap_kobo - total
        return success(
            f"{holder}: {format_naira(total)} to meter {args['meter_number']}. Confirm to charge.",
            {
                "status": "needs_confirmation",
                "customer_name": holder,
                "amount_kobo": total,
                "balance_after_kobo": after,
            },
        )
    placed = await ctx.charge("quick_buy", args, total, {"customer_name": holder})
    if args["meter_type"] == "prepaid" and not placed.error and placed.data.get("status") == "completed":
        return ToolAnswer({**placed.data, "token": TOKEN}, f"{placed.text} Token: {TOKEN}", fate=placed.fate)
    return placed


async def quick_buy(ctx: SimContext, args: dict[str, Any]) -> ToolAnswer:
    if ctx.account is None:
        return refusal("This needs a person's own Index account.")
    category = args["category"]
    if category == "data":
        return success("Bundles", {"bundles": BUNDLES})
    total, bad = _amount(args)
    if bad:
        return bad
    if category == "airtime":
        return await _airtime(ctx, args, total)
    return await _electricity(ctx, args, total)
