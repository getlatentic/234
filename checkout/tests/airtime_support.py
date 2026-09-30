# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the airtime flow tests: a quote request, an approval, a paid order, and a VTpass that is down."""

from checkout.errors import DomainError
from checkout.vtpass.api import AccessCheck

_counter = 0


def quote_input(**over):
    global _counter
    _counter += 1
    return {
        "network": "mtn",
        "phone": "08011111111",
        "amount_kobo": 50_000,
        "amount_as_user_said": "₦500",
        "idempotency_key": f"airtime-key-{_counter:04d}",
        **over,
    }


async def code_of(work) -> str:
    try:
        await work
    except DomainError as error:
        return error.code
    return "none"


async def vtpass_orders(stack) -> int:
    return await stack.count("sim_vtpass")


async def approve(flow, issued, amount=50_000, **over):
    args = {"readback_confirmed": True, **over}
    return await flow.approve(issued.quote["id"], issued.approval_token, amount, args["readback_confirmed"])


async def paid(stack, **over):
    """A quote approved and paid for on the simulated checkout; returns its id."""
    flow = stack.airtime
    issued = await flow.create_airtime_quote(**quote_input(**over))
    view = await approve(flow, issued)
    await stack.complete_checkout(view["checkoutUrl"], "success")
    return issued.quote["id"]


class Unreachable:
    """A VTpass that cannot be reached, whatever it is asked."""

    async def check_access(self):
        return AccessCheck(False, reason="VTpass could not be reached.")
