# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated Bachs checkout page, served at /sim/bachs/<checkout id> in simulated mode only: a stand-in
for Bachs' hosted page, where a top-up is "paid". It moves no money. A payment made here is announced as
Bachs announces one: a `collection.succeeded` body signed with the simulator's secret, handed to the same
/hooks/bachs code a real delivery reaches, so the wallet is credited by exactly the path Bachs' webhook
takes."""

import json

from .app import App
from .bachs.api import kobo_of
from .bachs.events import COLLECTION_SUCCEEDED
from .bachs.signature import SIGNATURE_HEADER, header_for
from .bachs.sim import iso
from .bachs.sim_store import SimCheckout
from .money import format_naira
from .responses import HTML_HEADERS, HttpResponse
from .sim_checkout import PAGE_HEADERS, same_origin
from .sim_checkout_page import buttons, page, state

TITLE = "Simulated Bachs checkout"
WHO = "Add money to your 234 wallet"
BASE = "/sim/bachs"
CHOICES = (("pay", "primary", "Pay by bank transfer"), ("close", "quiet", "Close without paying"))


def collection_body(checkout: SimCheckout, at_ms: int) -> bytes:
    """What Bachs sends when a checkout is paid, in the documented shape, with the checkout's own terms."""
    event = {
        "id": f"evt_{checkout.checkout_id.removeprefix('chk_')}",
        "type": COLLECTION_SUCCEEDED,
        "created_at": iso(at_ms),
        "data": {
            "checkout_id": checkout.checkout_id,
            "reference": checkout.reference,
            "status": "SUCCEEDED",
            "amount": checkout.amount,
            "currency": checkout.currency,
            "fee_bearer": "merchant",
            "metadata": checkout.metadata,
        },
    }
    return json.dumps(event).encode()


async def _announce(app: App, checkout: SimCheckout) -> int:
    now = app.clock.now()
    body = collection_body(checkout, now)
    headers = {SIGNATURE_HEADER: header_for(app.funding.hook.secrets, now // 1000, body)}
    return (await app.funding.hook.answer(headers, body)).status


def _body(checkout: SimCheckout, now: int, closed: bool) -> tuple[str, bool]:
    if checkout.status == "paid":
        return state("paid", "Paid", None), True
    if checkout.expires_at <= now:
        return state("closed", "Expired", None), True
    if closed:
        return state("closed", "Closed", None), True
    return buttons(checkout.checkout_id, "", BASE, CHOICES), False


async def handle_bachs_checkout(app: App, method: str, path: str, headers: dict[str, str]) -> HttpResponse:
    parts = path.strip("/").split("/")  # sim / bachs / <checkout id> [/ pay|close]
    store = app.funding.sim
    checkout = await store.checkout(parts[2]) if store and len(parts) >= 3 else None
    if store is None or checkout is None:
        return HttpResponse(404, "Unknown checkout", HTML_HEADERS)
    action = parts[3] if method == "POST" and len(parts) == 4 and parts[3] in ("pay", "close") else None
    if method == "POST" and action is None:
        return HttpResponse(404, "Not found", HTML_HEADERS)
    if action and not same_origin(app, headers):
        return HttpResponse(403, "Refused: this page only takes its own buttons", HTML_HEADERS)
    if action == "pay" and await store.pay(checkout.checkout_id, app.clock.now()):
        checkout = await store.checkout(checkout.checkout_id) or checkout
        await _announce(app, checkout)
    body, closing = _body(checkout, app.clock.now(), action == "close")
    amount = format_naira(kobo_of(checkout.amount) or 0)
    return HttpResponse(200, page(WHO, amount, body, closing=closing, title=TITLE), PAGE_HEADERS)
