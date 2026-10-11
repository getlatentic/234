# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator routes under /ops/, for a person who holds OPS_TOKEN: corrections to a wallet
(POST /ops/wallet/adjust, wallet/adjustments.py) and the wallet's reconciliation, run now
(GET /ops/wallet/reconcile, wallet/reconciliation.py). A request without the token, or to a Worker that has
none set, is answered 404, as if the route did not exist."""

import hmac
import json

from .app import App
from .errors import DomainError
from .responses import HttpResponse, json_response
from .wallet.correction import correction_of

MAX_BODY = 8 * 1024
STATUS = {"INVALID_INPUT": 400, "CORRECTION_CONFLICT": 409}
ADJUST, RECONCILE = ["ops", "wallet", "adjust"], ["ops", "wallet", "reconcile"]


def holds_ops_token(app: App, headers: dict[str, str]) -> bool:
    expected = app.settings.ops_token
    given = headers.get("authorization", "").removeprefix("Bearer ").strip()
    return bool(expected) and hmac.compare_digest(given.encode(), (expected or "").encode())


async def handle_ops(
    app: App, method: str, parts: list[str], headers: dict[str, str], raw: bytes
) -> HttpResponse:
    if not holds_ops_token(app, headers) or parts not in (ADJUST, RECONCILE):
        return HttpResponse(404, "Not found")
    if parts == RECONCILE:
        if method != "GET":
            return HttpResponse(405, "", {"allow": "GET"})
        return json_response((await app.reconciliation.run()).view())
    if method != "POST":
        return HttpResponse(405, "", {"allow": "POST"})
    if len(raw) > MAX_BODY:
        return HttpResponse(413, "Too large")
    try:
        body = json.loads(raw or b"null")
    except ValueError:
        return _refusal(DomainError("INVALID_INPUT", "The body is not JSON."))
    try:
        return await _adjust(app, body)
    except DomainError as error:
        return _refusal(error)


async def _adjust(app: App, body: object) -> HttpResponse:
    asked = correction_of(body)
    found, moved = await app.adjustments.adjust(asked)
    balance = await app.adjustments.journal.balance(asked.owner)
    answer = {"correction": found.view(), "moved": moved, "balanceKobo": balance}
    return json_response(answer, 200 if found.state == "applied" else 202)


def _refusal(error: DomainError) -> HttpResponse:
    body = {"error": {"code": error.code, "message": error.message}}
    return json_response(body, STATUS.get(error.code, 422))
