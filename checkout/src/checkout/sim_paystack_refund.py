# SPDX-License-Identifier: AGPL-3.0-or-later
"""A simulated Paystack refund moved on by a test route (testing_routes.py, ENABLE_TEST_ROUTES=1): the
undecided refunds of a payment take the status asked for, and the move is announced as Paystack announces one,
a `refund.<status>` event naming the payment by `transaction_reference`
(https://paystack.com/docs/payments/refunds/), signed with the simulator's key and handed to the same
/hooks/paystack code a real delivery reaches."""

import json

from .app import App
from .provider_hooks import paystack as paystack_webhook
from .provider_hooks.http import paystack_hook
from .responses import HttpResponse, json_response

STATUSES = ("processing", "needs-attention", "failed", "processed")


def refund_event(reference: str, status: str, amount_kobo: int) -> bytes:
    """Paystack's refund event: the amount a string, and no refund id."""
    body = {
        "event": f"refund.{status}",
        "data": {
            "status": status,
            "transaction_reference": reference,
            "refund_reference": None,
            "amount": str(amount_kobo),
            "currency": "NGN",
            "domain": "test",
        },
    }
    return json.dumps(body).encode()


async def move_refund(app: App, reference: str, status: str) -> HttpResponse:
    if status not in STATUSES:
        return HttpResponse(400, "Unknown refund status")
    transaction = await app.paystack_sim.transaction(reference)
    moved = await app.paystack_sim.set_refund_status(reference, status) if transaction else 0
    if transaction is None or moved == 0:
        return HttpResponse(404, "No undecided simulated refund of that payment")
    body = refund_event(reference, status, transaction.amount_kobo)
    key = paystack_webhook.simulated_key(app.settings.approval_secret)
    headers = {paystack_webhook.SIGNATURE_HEADER: paystack_webhook.sign(body, key)}
    answer = await paystack_hook(app.background.rechecks, (key,), headers, body)
    return json_response({"moved": moved, "hookStatus": answer.status})
