# SPDX-License-Identifier: AGPL-3.0-or-later
"""A simulated merchant's answer to an order, set by a test route (testing_routes.py, ENABLE_TEST_ROUTES=1):
the order of a `merchants` quote answers delivered, pending or failed, as a merchant would answer the message
fulfilment sends it (commerce/simulated.py). Set before the quote is paid, the answer is what fulfilment
finds; set while the order is pending, it moves it, and the quote is asked about again as a provider's
callback would have it asked."""

from .app import App
from .commerce.simulated import ANSWERS, SimMerchants
from .flows.merchant_leg import CONNECTOR
from .responses import HttpResponse, json_response


async def move_merchant_order(app: App, quote_id: str, outcome: str) -> HttpResponse:
    if outcome not in ANSWERS:
        return HttpResponse(400, "Unknown merchant outcome")
    quote = await app.db.row("SELECT connector FROM quotes WHERE id = ?", quote_id)
    if quote is None or quote["connector"] != CONNECTOR:
        return HttpResponse(404, "No such merchants quote")
    answered = await SimMerchants(app.db, app.clock).preset(quote_id, outcome)
    asked = await app.background.rechecks.ask(quote_id, "merchant")
    return json_response({"outcome": answered.status, "asked": asked})
