# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /hooks/paystack and POST /hooks/vtpass. Each answers at once: the quote a webhook names is checked
again later, by a job (rechecks.py)."""

from ..responses import HttpResponse, json_response
from . import paystack, vtpass
from .rechecks import Rechecks

MAX_BODY = 64 * 1024


def paystack_keys(secret_key: str | None, approval_secret: str) -> tuple[str, ...]:
    """Paystack signs with the account's secret key, the simulator with a key from the approval secret."""
    return tuple(k for k in (secret_key, paystack.simulated_key(approval_secret)) if k)


async def paystack_hook(
    rechecks: Rechecks, keys: tuple[str, ...], headers: dict[str, str], raw: bytes
) -> HttpResponse:
    if len(raw) > MAX_BODY:
        return HttpResponse(413, "Too large")
    signature = headers.get(paystack.SIGNATURE_HEADER, "")
    if not any(paystack.is_genuine(raw, signature, key) for key in keys):
        return HttpResponse(401, "Unsigned")
    await rechecks.ask(paystack.quote_of(raw), "paystack")
    return json_response({"received": True})


async def vtpass_hook(rechecks: Rechecks, raw: bytes) -> HttpResponse:
    if len(raw) > MAX_BODY:
        return HttpResponse(413, "Too large")
    await rechecks.ask(vtpass.quote_of(raw), "vtpass")
    return json_response(vtpass.ACKNOWLEDGED)
