# SPDX-License-Identifier: AGPL-3.0-or-later
"""The slice of VTpass the airtime connector uses."""

from dataclasses import dataclass
from typing import Literal, Protocol

from ..money import Kobo
from ..network import Network

AIRTIME_SERVICE: dict[str, str] = {"mtn": "mtn", "airtel": "airtel", "glo": "glo", "9mobile": "etisalat"}
DATA_SERVICE: dict[str, str] = {
    "mtn": "mtn-data",
    "airtel": "airtel-data",
    "glo": "glo-data",
    "9mobile": "etisalat-data",
}


class VtpassError(Exception):
    pass


@dataclass(frozen=True)
class AirtimeOrder:
    request_id: str
    network: Network
    phone: str
    amount_kobo: Kobo


@dataclass(frozen=True)
class DataOrder:
    request_id: str
    network: Network
    phone: str
    plan_code: str
    amount_kobo: Kobo


@dataclass(frozen=True)
class DataPlan:
    code: str
    name: str
    amount_kobo: Kobo


@dataclass(frozen=True)
class VtpassOutcome:
    """What VTpass said about an order, in the three states the card can show. `pending` also covers a
    reply that never came: the order may still go through. `unknown_request` is true when VTpass says
    it never saw the request id, so the same order can be sent again."""

    status: Literal["delivered", "pending", "failed"]
    code: str | None
    description: str
    unknown_request: bool = False


@dataclass(frozen=True)
class AccessCheck:
    """Whether VTpass will take orders from this account, and what its wallet holds when it says."""

    ok: bool
    balance_kobo: Kobo | None = None
    reason: str = ""


class VtpassApi(Protocol):
    async def check_access(self) -> AccessCheck:
        """Asks for the wallet balance, which needs valid credentials. Used before a quote, so nobody
        pays for what cannot be delivered."""
        ...

    async def buy_airtime(self, order: AirtimeOrder) -> VtpassOutcome: ...

    async def buy_data(self, order: DataOrder) -> VtpassOutcome: ...

    async def requery(self, request_id: str) -> VtpassOutcome: ...

    async def data_plans(self, network: Network) -> list[DataPlan]: ...
