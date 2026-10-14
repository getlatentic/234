# SPDX-License-Identifier: AGPL-3.0-or-later
"""The slice of VTpass that pays television subscriptions and electricity: the services, what an account check
returns, what an order carries, and how the replies read (https://vtpass.com/documentation/, read 2026-10-14).

An account check (`merchant-verify`) answers `000` for a reply and puts the verdict in its content. A meter or
smartcard VTpass does not know comes back as `WrongBillersCode` or as an `error`, and a meter it cannot vend
to as `Can_Vend` false: each is refused here and never reaches a quote. A pay or requery reply is read by
`interpret_vtpass` like any other; `receipt.bill_receipt` takes what a delivered one gives the buyer."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from ..money import Kobo
from .api import VtpassError

BillKind = Literal["tv", "electricity"]

# serviceID -> (kind, name). The twelve distribution companies are the ones the documentation lists.
SERVICES: dict[str, tuple[BillKind, str]] = {
    "dstv": ("tv", "DStv"),
    "gotv": ("tv", "GOtv"),
    "startimes": ("tv", "StarTimes"),
    "showmax": ("tv", "Showmax"),
    "ikeja-electric": ("electricity", "Ikeja Electric (IKEDC)"),
    "eko-electric": ("electricity", "Eko Electricity (EKEDC)"),
    "kano-electric": ("electricity", "Kano Electricity (KEDCO)"),
    "portharcourt-electric": ("electricity", "Port Harcourt Electricity (PHED)"),
    "jos-electric": ("electricity", "Jos Electricity (JED)"),
    "ibadan-electric": ("electricity", "Ibadan Electricity (IBEDC)"),
    "kaduna-electric": ("electricity", "Kaduna Electric (KAEDCO)"),
    "abuja-electric": ("electricity", "Abuja Electricity (AEDC)"),
    "enugu-electric": ("electricity", "Enugu Electricity (EEDC)"),
    "benin-electric": ("electricity", "Benin Electricity (BEDC)"),
    "aba-electric": ("electricity", "Aba Power (ABA)"),
    "yola-electric": ("electricity", "Yola Electricity (YEDC)"),
}
RENEWABLE = frozenset({"dstv", "gotv"})
"""The services whose subscription is renewed at the amount the check returns, or changed to a bouquet."""
_CANNOT_VEND = frozenset({"false", "no", "0", "n"})
_WRONG = (None, False, "false", "False", "FALSE", "", 0)


@dataclass(frozen=True)
class Bouquet:
    code: str
    name: str
    amount_kobo: Kobo


@dataclass(frozen=True)
class BillAccount:
    """What `merchant-verify` found. Every field but the holder may be missing: the documentation's own sample
    of a television check lacks the current bouquet and the renewal amount."""

    holder: str
    address: str | None = None
    bouquet: str | None = None
    renewal_kobo: Kobo | None = None
    due_date: str | None = None
    arrears_kobo: Kobo | None = None
    min_kobo: Kobo | None = None
    max_kobo: Kobo | None = None
    meter_type: str | None = None
    account_type: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class BillCheck:
    service_id: str
    billers_code: str
    meter_type: str | None = None


@dataclass(frozen=True)
class BillOrder:
    request_id: str
    service_id: str
    billers_code: str
    phone: str
    amount_kobo: Kobo
    variation_code: str | None = None
    subscription_type: str | None = None
    meter_type: str | None = None
    quantity: int | None = None
    """Months of viewing, for a subscription that is paid for by the month."""


class BillRefused(VtpassError):
    """VTpass does not know the smartcard or meter, or will not vend to it: no quote is made."""


def verify_body(check: BillCheck) -> dict[str, Any]:
    return {
        "billersCode": check.billers_code,
        "serviceID": check.service_id,
        **({"type": check.meter_type} if check.meter_type else {}),
    }


def pay_body(order: BillOrder) -> dict[str, Any]:
    """The `pay` request: a meter's type rides as `variation_code`, a renewal carries no bouquet, and the
    amount is in naira, whole when it is whole."""
    naira = order.amount_kobo // 100 if order.amount_kobo % 100 == 0 else order.amount_kobo / 100
    variation = order.variation_code or order.meter_type
    return {
        "request_id": order.request_id,
        "serviceID": order.service_id,
        "billersCode": order.billers_code,
        "amount": naira,
        "phone": order.phone,
        **({"variation_code": variation} if variation else {}),
        **({"subscription_type": order.subscription_type} if order.subscription_type else {}),
        **({"quantity": order.quantity} if order.quantity else {}),
    }


def kobo_of(value: Any) -> Kobo | None:
    """A naira figure as VTpass writes it (`"1850.00"`, `500`, `""`) in kobo; None when there is none."""
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        naira = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None
    return (
        int((naira * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        if naira.is_finite() and naira >= 0
        else None
    )


def _text(content: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = content.get(name)
        if isinstance(value, str | int) and not isinstance(value, bool) and str(value).strip():
            return str(value).strip()
    return None


def _money(content: dict[str, Any], *names: str) -> Kobo | None:
    return next((kobo for kobo in (kobo_of(content.get(name)) for name in names) if kobo), None)


def _refusal(payload: Any) -> BillRefused | None:
    content = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(content, dict):
        return BillRefused("VTpass did not confirm the account.")
    if content.get("WrongBillersCode") not in _WRONG:
        return BillRefused("VTpass does not know that number.")
    if content.get("error"):
        return BillRefused("VTpass could not verify that number.")
    can_vend = content.get("Can_Vend")
    if can_vend is not None and str(can_vend).strip().lower() in _CANNOT_VEND:
        return BillRefused("VTpass says this meter cannot be sold to right now.")
    if _text(content, "Customer_Name") is None:
        return BillRefused("VTpass returned no holder for that number.")
    return None


def account_from(payload: Any) -> BillAccount:
    """The account a `merchant-verify` reply describes, or the refusal."""
    if refusal := _refusal(payload):
        raise refusal
    content: dict[str, Any] = payload["content"]
    return BillAccount(
        holder=_text(content, "Customer_Name") or "",
        address=_text(content, "Address"),
        bouquet=_text(content, "Current_Bouquet"),
        renewal_kobo=_money(content, "Renewal_Amount"),
        due_date=_text(content, "Due_Date"),
        arrears_kobo=_money(content, "Customer_Arrears"),
        min_kobo=_money(content, "Minimum_Amount", "Min_Purchase_Amount"),
        max_kobo=_money(content, "MAX_Purchase_Amount", "Max_Purchase_Amount", "Maximum_Amount"),
        meter_type=_text(content, "Meter_Type"),
        account_type=_text(content, "Customer_Account_Type"),
        status=_text(content, "Status"),
    )


def bouquets_from(payload: Any) -> list[Bouquet]:
    """The fixed-price bouquets a `service-variations` reply lists."""
    content = payload.get("content") if isinstance(payload, dict) else None
    listed = content.get("variations") if isinstance(content, dict) else None
    if not isinstance(listed, list):
        raise VtpassError("VTpass did not return a list of bouquets.")
    found = [
        Bouquet(v["variation_code"], v["name"], amount)
        for v in listed
        if isinstance(v, dict)
        and isinstance(v.get("variation_code"), str)
        and isinstance(v.get("name"), str)
        and v.get("fixedPrice") != "No"
        and (amount := kobo_of(v.get("variation_amount")))
    ]
    if not found:
        raise VtpassError("VTpass listed no bouquets.")
    return found
