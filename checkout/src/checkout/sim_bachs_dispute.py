# SPDX-License-Identifier: AGPL-3.0-or-later
"""A chargeback on a simulated Bachs charge, raised and moved on by a test route (testing_routes.py,
ENABLE_TEST_ROUTES=1) in simulated mode only. Each call is announced as Bachs announces a dispute: a
`dispute.created` or `dispute.updated` body in the documented shape, signed with the simulator's secret and
handed to the same /hooks/bachs code a real delivery reaches. The dispute's id follows from the charge, so the
calls for one charge are one dispute."""

import json

from .app import App
from .bachs.api import kobo_of
from .bachs.sim import iso
from .bachs.sim_store import SimCheckout
from .responses import HttpResponse, json_response
from .sim_bachs import announce, charge_of

STATUSES = ("needs_response", "under_review", "won", "lost", "closed", "prevented")
EVENTS = ("dispute.created", "dispute.updated")
DAY_MS = 86_400_000


def dispute_id_of(checkout: SimCheckout) -> str:
    return f"dsp_{checkout.checkout_id.removeprefix('chk_')}"


def dispute_body(checkout: SimCheckout, event: str, status: str, amount: str, at_ms: int) -> bytes:
    """What Bachs sends about a dispute on this checkout's charge; `amount` is a decimal string, as Bachs'."""
    body = {
        "id": f"evt_{event.split('.')[1]}_{status}_{checkout.checkout_id.removeprefix('chk_')}",
        "type": event,
        "created_at": iso(at_ms),
        "data": {
            "dispute_id": dispute_id_of(checkout),
            "charge_id": charge_of(checkout),
            "amount": amount,
            "currency": checkout.currency,
            "status": status,
            "reason": "fraudulent",
            "response_deadline_at": iso(at_ms + 7 * DAY_MS),
            "charge_amount": checkout.amount,
            "charge_currency": checkout.currency,
        },
    }
    return json.dumps(body).encode()


async def raise_dispute(
    app: App, checkout_id: str, event: str, status: str, amount: str | None
) -> HttpResponse:
    """`amount` defaults to the whole charge."""
    store = app.funding.sim
    checkout = await store.checkout(checkout_id) if store else None
    if checkout is None or checkout.status != "paid":
        return HttpResponse(404, "No paid simulated checkout of that id")
    disputed = amount or checkout.amount
    if event not in EVENTS or status not in STATUSES or kobo_of(disputed) is None:
        return HttpResponse(400, "Unknown event, status or amount")
    body = dispute_body(checkout, event, status, disputed, app.clock.now())
    return json_response({"dispute": dispute_id_of(checkout), "hookStatus": await announce(app, body)})
