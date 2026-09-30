# SPDX-License-Identifier: AGPL-3.0-or-later
"""A VTpass that answers from local state, for the public simulated demo and for tests. It is a
`Transport`, so the real client talks to it unchanged.

It differs from the real VTpass sandbox on purpose. The sandbox delivers only 08011111111 and fails "any
other number", which is right for testing an integration but wrong for a public demo: a visitor who pays
with their own real number would be told the delivery failed. Here any valid Nigerian mobile number is
delivered. The sandbox's documented trigger numbers keep their outcomes: 201000000000 stays pending,
and 500000000000 (unexpected reply), 400000000000 (no reply) and 300000000000 (timeout) count as pending.
The sandbox has no number that means failure, so the simulator adds 100000000000 for it, and a number
that is not a valid Nigerian mobile still fails. `VTPASS_MODE=sandbox` uses the real sandbox and its rules.
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..clock import Clock
from ..transport import Reply, TransportError
from .phone import DOCUMENTED_SUCCESS_NUMBER, SIMULATED_FAILURE_NUMBER, is_nigerian_mobile
from .plans import simulated_variations
from .sim_store import SimOrder, VtpassSimStore

SCENARIO_BY_PHONE = {
    DOCUMENTED_SUCCESS_NUMBER: "success",
    SIMULATED_FAILURE_NUMBER: "failed",
    "201000000000": "pending",
    "500000000000": "unexpected",
    "400000000000": "no_reply",
    "300000000000": "timeout",
}
DEFAULT_BALANCE_NAIRA = 100_000
MINIMUM_AIRTIME_NAIRA = 50


def _json_reply(body: Any, status: int = 200) -> Reply:
    return Reply(status, json.dumps(body), "application/json")


def _text(value: Any) -> str:
    return str(value) if isinstance(value, str | int | float) and not isinstance(value, bool) else ""


def _iso(at: int) -> str:
    return datetime.fromtimestamp(at / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _transaction_body(order: SimOrder, status: str, code: str, description: str, now: int) -> dict[str, Any]:
    return {
        "code": code,
        "response_description": description,
        "content": {
            "transactions": {
                "status": status,
                "product_name": order.service_id,
                "unique_element": order.phone,
                "unit_price": _text(_whole(order.amount_naira)),
                "quantity": 1,
                "type": "Data Services" if order.variation_code else "Airtime Recharge",
                "transactionId": f"SIM{order.created_at}",
            }
        },
        "requestId": order.request_id,
        "amount": _whole(order.amount_naira),
        "transaction_date": _iso(now),
        "purchased_code": "",
    }


def _whole(amount: float) -> int | float:
    return int(amount) if amount == int(amount) else amount


def _refused() -> Reply:
    """What the real sandbox sent, observed 2026-09-29, for an account whose credentials it would not "
    "accept."""
    return _json_reply("Invalid Credentials.", 401)


def _bad_keys() -> Reply:
    """What the real sandbox sent for a request with missing or mismatched keys, observed 2026-09-29."""
    return _json_reply({"code": "087", "message": "INVALID CREDENTIALS"}, 401)


class VtpassSimulator:
    def __init__(
        self,
        store: VtpassSimStore,
        clock: Clock,
        *,
        pending_seconds: int = 20,
        reject_credentials: bool = False,
        balance_naira: float = DEFAULT_BALANCE_NAIRA,
    ) -> None:
        self._store = store
        self._clock = clock
        self._pending_ms = pending_seconds * 1000
        self._reject = reject_credentials
        self._balance = balance_naira

    async def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: str | None,
        timeout_seconds: float,
    ) -> Reply:
        del timeout_seconds
        parts = urlsplit(url)
        route = f"{method} {parts.path.removeprefix('/api')}"
        if self._reject and route != "GET /service-variations":
            return _refused()
        present = {k.lower() for k in headers}
        if "api-key" not in present or ("public-key" if method == "GET" else "secret-key") not in present:
            return _bad_keys()
        payload = _json_object(body)
        match route:
            case "POST /pay":
                return await self._purchase(payload)
            case "POST /requery":
                return await self._requery(payload)
            case "GET /service-variations":
                return _variations(parse_qs(parts.query).get("serviceID", [""])[0])
            case "GET /balance":
                return _json_reply({"code": 1, "contents": {"balance": self._balance}})
            case _:
                return Reply(404, "Not found", "text/plain")

    async def _purchase(self, body: dict[str, Any]) -> Reply:
        now = self._clock.now()
        order = _parse_order(body, now)
        if isinstance(order, Reply):
            return order
        if not await self._store.add(order):
            return _json_reply({"code": "014", "response_description": "REQUEST ID ALREADY EXIST"})
        return _first_reply(order, now)

    async def _requery(self, body: dict[str, Any]) -> Reply:
        order = await self._store.get(_text(body.get("request_id")))
        if order is None:
            return _json_reply({"code": "015", "response_description": "INVALID REQUEST ID"})
        return self._status_now(order)

    def _status_now(self, order: SimOrder) -> Reply:
        now = self._clock.now()
        delivered = _transaction_body(order, "delivered", "000", "TRANSACTION SUCCESSFUL", now)
        match order.scenario:
            case "success":
                return _json_reply(delivered)
            case "failed":
                return _json_reply(_transaction_body(order, "failed", "000", "TRANSACTION FAILED", now))
            case _:
                if now - order.created_at >= self._pending_ms:
                    return _json_reply(delivered)
                return _json_reply(_transaction_body(order, "pending", "000", "TRANSACTION PENDING", now))


def _json_object(body: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(body) if body else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _amount(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_order(body: dict[str, Any], now: int) -> SimOrder | Reply:
    request_id, service_id, phone = (
        _text(body.get("request_id")),
        _text(body.get("serviceID")),
        _text(body.get("phone")),
    )
    variation = _text(body.get("variation_code")) or None
    amount = _amount(body.get("amount"))
    if not request_id or not service_id or not phone:
        return _json_reply({"code": "011", "response_description": "INVALID ARGUMENTS"})
    if variation is None and (amount is None or amount < MINIMUM_AIRTIME_NAIRA):
        return _json_reply({"code": "013", "response_description": "BELOW MINIMUM AMOUNT ALLOWED"})
    scenario = SCENARIO_BY_PHONE.get(phone) or ("success" if is_nigerian_mobile(phone) else "failed")
    return SimOrder(request_id, service_id, phone, amount or 0.0, variation, scenario, now)


def _first_reply(order: SimOrder, now: int) -> Reply:
    match order.scenario:
        case "success":
            return _json_reply(_transaction_body(order, "delivered", "000", "TRANSACTION SUCCESSFUL", now))
        case "pending":
            return _json_reply(_transaction_body(order, "pending", "000", "TRANSACTION PENDING", now))
        case "unexpected":
            return _json_reply({"code": "999", "response_description": "UNEXPECTED RESPONSE"})
        case "no_reply":
            raise TransportError("fetch failed")
        case "timeout":
            raise TransportError("The operation timed out.")
        case _:
            return _json_reply({"code": "016", "response_description": "TRANSACTION FAILED"})


def _variations(service_id: str) -> Reply:
    found = simulated_variations(service_id)
    if found is None:
        return _json_reply({"response_description": "012", "code": "012"})
    name, plans = found
    return _json_reply(
        {
            "response_description": "000",
            "content": {"ServiceName": name, "serviceID": service_id, "variations": plans},
        }
    )
