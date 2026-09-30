# SPDX-License-Identifier: AGPL-3.0-or-later
"""The VTpass client. It talks only to the sandbox host: there is no setting for a live VTpass URL."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, ValidationError

from ..clock import Clock, SystemClock
from ..network import Network
from ..transport import Reply, Transport, TransportError
from .api import (
    AIRTIME_SERVICE,
    DATA_SERVICE,
    AccessCheck,
    AirtimeOrder,
    DataOrder,
    DataPlan,
    VtpassError,
    VtpassOutcome,
)
from .interpret import interpret_vtpass, no_confirmation

VTPASS_SANDBOX_URL = "https://sandbox.vtpass.com/api"
DEFAULT_TIMEOUT_SECONDS = 20.0
ACCESS_CACHE_MS = 60_000
_LONG_TOKEN = re.compile(r"[A-Za-z0-9]{20,}")


@dataclass(frozen=True)
class VtpassCredentials:
    api_key: str = field(repr=False)
    public_key: str = field(repr=False)
    secret_key: str = field(repr=False)


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class _Variation(_Model):
    variation_code: str
    name: str
    variation_amount: str
    fixedPrice: str | None = None


class _Content(_Model):
    variations: list[_Variation]


class _PlansReply(_Model):
    content: _Content


class _Contents(_Model):
    balance: float


class _BalanceReply(_Model):
    code: int | str
    contents: _Contents


def describe_reply(status: int, content_type: str | None, body: str) -> str:
    """One line about a reply for debugging: status, content type, length and the first 300 characters of
    the body with any run of 20 or more letters and digits replaced, and never a request."""
    shown = re.sub(r"\s+", " ", _LONG_TOKEN.sub("[redacted]", body[:300]))
    return (
        f"vtpass reply: HTTP {status} content-type={content_type or 'none'} length={len(body)} body={shown}"
    )


def _kobo_of(amount: str) -> int:
    return int((Decimal(amount) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _naira(kobo: int) -> int | float:
    return kobo // 100 if kobo % 100 == 0 else kobo / 100


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


class VtpassClient:
    def __init__(
        self,
        credentials: VtpassCredentials,
        transport: Transport,
        *,
        clock: Clock | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        debug: Callable[[str], None] | None = None,
    ) -> None:
        self._credentials = credentials
        self._transport = transport
        self._clock = clock or SystemClock()
        self._timeout = timeout_seconds
        self._debug = debug
        self._access: tuple[int, AccessCheck] | None = None

    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Reply | None:
        """The reply, or None when nothing readable came back."""
        c = self._credentials
        headers = {
            "Content-Type": "application/json",
            "api-key": c.api_key,
            **({"public-key": c.public_key} if method == "GET" else {"secret-key": c.secret_key}),
        }
        try:
            reply = await self._transport.send(
                method,
                f"{VTPASS_SANDBOX_URL}{path}",
                headers=headers,
                body=None if body is None else json.dumps(body),
                timeout_seconds=self._timeout,
            )
        except TransportError:
            return None
        if self._debug:
            self._debug(describe_reply(reply.status, reply.content_type, reply.body))
        return reply

    async def _outcome(self, path: str, body: dict[str, Any]) -> VtpassOutcome:
        reply = await self._request("POST", path, body)
        if reply is None:
            return no_confirmation("no reply")
        return interpret_vtpass(_json(reply.body), reply.status)

    async def buy_airtime(self, order: AirtimeOrder) -> VtpassOutcome:
        return await self._outcome(
            "/pay",
            {
                "request_id": order.request_id,
                "serviceID": AIRTIME_SERVICE[order.network],
                "amount": _naira(order.amount_kobo),
                "phone": order.phone,
            },
        )

    async def buy_data(self, order: DataOrder) -> VtpassOutcome:
        return await self._outcome(
            "/pay",
            {
                "request_id": order.request_id,
                "serviceID": DATA_SERVICE[order.network],
                "billersCode": order.phone,
                "variation_code": order.plan_code,
                "amount": _naira(order.amount_kobo),
                "phone": order.phone,
            },
        )

    async def requery(self, request_id: str) -> VtpassOutcome:
        return await self._outcome("/requery", {"request_id": request_id})

    async def check_access(self) -> AccessCheck:
        """The wallet balance doubles as a credentials check. A good answer is remembered for a minute."""
        now = self._clock.now()
        if self._access and now - self._access[0] < ACCESS_CACHE_MS and self._access[1].ok:
            return self._access[1]
        result = await self._ask_for_balance()
        self._access = (now, result)
        return result

    async def _ask_for_balance(self) -> AccessCheck:
        reply = await self._request("GET", "/balance")
        if reply is None:
            return AccessCheck(False, reason="VTpass could not be reached.")
        if reply.status in (401, 403):
            return AccessCheck(
                False, reason=f"VTpass refused this account's credentials (HTTP {reply.status})."
            )
        try:
            parsed = _BalanceReply.model_validate(_json(reply.body))
        except ValidationError:
            return AccessCheck(False, reason="VTpass did not return a wallet balance.")
        return AccessCheck(True, balance_kobo=_kobo_of(str(parsed.contents.balance)))

    async def data_plans(self, network: Network) -> list[DataPlan]:
        reply = await self._request(
            "GET", f"/service-variations?serviceID={quote(DATA_SERVICE[network], safe='')}"
        )
        try:
            parsed = _PlansReply.model_validate(_json(reply.body) if reply else None)
        except ValidationError as error:
            raise VtpassError("VTpass did not return a list of data plans.") from error
        return [
            DataPlan(v.variation_code, v.name, _kobo_of(v.variation_amount))
            for v in parsed.content.variations
            if v.fixedPrice != "No"
        ]
