# SPDX-License-Identifier: AGPL-3.0-or-later
"""The simulated VTpass's television and electricity: what an account check answers, how an order is
judged, and what a delivered one gives the buyer. The scenarios are the ones the documentation lists
(https://vtpass.com/documentation/, read 2026-10-14), keyed by the smartcard or meter in `billersCode`:

- smartcard 1212121212 and meters 1111111111111 (prepaid) and 1010101010101 (postpaid) succeed;
- 201000000000 is pending, 500000000000 answers unexpectedly, 400000000000 does not answer, 300000000000
  times out, and any other number fails.

It differs from the sandbox in two ways, on purpose. The sandbox verifies only its success numbers, so a
pending order could not be demonstrated through an account check; here the trigger numbers and 100000000000,
which fails like any other number the sandbox does not know, are verified as accounts and then behave as their
scenario says. And Showmax, which has no check and takes the subscriber's phone as `billersCode`, delivers to
any valid Nigerian mobile number as the simulated airtime does."""

import hashlib
from typing import Any

from .bills import SERVICES
from .phone import DOCUMENTED_SUCCESS_NUMBER, SIMULATED_FAILURE_NUMBER, is_nigerian_mobile
from .sim_store import SimOrder

TRIGGERS = {
    "201000000000": "pending",
    "500000000000": "unexpected",
    "400000000000": "no_reply",
    "300000000000": "timeout",
    SIMULATED_FAILURE_NUMBER: "failed",
}
SMARTCARD = "1212121212"
METERS = {"1111111111111": "prepaid", "1010101010101": "postpaid"}
TV_ACCOUNTS: dict[str, dict[str, Any]] = {
    "dstv": {"Customer_Name": "ADEOLA BALOGUN", "Current_Bouquet": "DStv Confam", "Renewal_Amount": 10500},
    "gotv": {"Customer_Name": "CHIOMA OKEKE", "Current_Bouquet": "GOtv Max", "Renewal_Amount": 8500},
    "startimes": {"Customer_Name": "IBRAHIM YUSUF", "Balance": 0},
}
HOLDERS = {"prepaid": "FUNMI AKINTOLA", "postpaid": "KELECHI NWOSU"}
ADDRESSES = {"prepaid": "12 ALLEN AVENUE, IKEJA", "postpaid": "4 ADEOLA ODEKU STREET, VICTORIA ISLAND"}
ARREARS = {"prepaid": "0.00", "postpaid": "8350.50"}
MINIMUM_NAIRA = {"ibadan-electric": "2000", "ikeja-electric": "1000"}
DEFAULT_MINIMUM_NAIRA = "500"
KWH_PRICE_NAIRA = 70.0
RENEWAL = "renew"


def is_bill(service_id: str) -> bool:
    return service_id in SERVICES


def type_of(order: SimOrder) -> str | None:
    """The `type` of a bill's transaction as VTpass names it; None for an order that is not a bill."""
    if order.service_id not in SERVICES:
        return None
    return "TV Subscription" if SERVICES[order.service_id][0] == "tv" else "Electricity Bill"


def _known(service_id: str, billers_code: str, meter_type: str | None) -> bool:
    """Whether the simulator has an account for this number: its success numbers and the trigger numbers."""
    if SERVICES[service_id][0] == "electricity":
        return billers_code in TRIGGERS or METERS.get(billers_code) == meter_type
    return billers_code in TRIGGERS or billers_code == SMARTCARD


def verify_body(payload: dict[str, Any]) -> dict[str, Any]:
    """The reply to `merchant-verify`: the account's content, or the sandbox's way of saying it is unknown."""
    service_id, code = str(payload.get("serviceID", "")), str(payload.get("billersCode", ""))
    meter_type = str(payload.get("type") or "")
    if service_id not in SERVICES or service_id == "showmax":
        return {"code": "012", "response_description": "PRODUCT DOES NOT EXIST"}
    if not _known(service_id, code, meter_type):
        return {"code": "000", "content": {"error": "Unable to verify the number", "WrongBillersCode": True}}
    content = (
        _electricity_content(service_id, code, meter_type)
        if SERVICES[service_id][0] == "electricity"
        else _tv_content(service_id, code)
    )
    return {"code": "000", "content": {**content, "WrongBillersCode": False}}


def _tv_content(service_id: str, code: str) -> dict[str, Any]:
    account = TV_ACCOUNTS[service_id]
    base = {"Status": "ACTIVE", "Customer_Number": code, "Customer_Type": service_id.upper()}
    if service_id == "startimes":
        return {**account, "Smartcard_Number": code}
    return {**account, **base, "Due_Date": "2026-11-02T00:00:00"}


def _electricity_content(service_id: str, code: str, meter_type: str) -> dict[str, Any]:
    kind = METERS.get(code, meter_type if meter_type in HOLDERS else "prepaid")
    return {
        "Customer_Name": HOLDERS[kind],
        "Address": ADDRESSES[kind],
        "Meter_Number": code,
        "Customer_Arrears": ARREARS[kind],
        "Minimum_Amount": "",
        "Min_Purchase_Amount": MINIMUM_NAIRA.get(service_id, DEFAULT_MINIMUM_NAIRA),
        "Can_Vend": "true",
        "Business_Unit": "SIMULATED",
        "Customer_Account_Type": "NMD",
        "Meter_Type": kind.upper(),
    }


def _scenario(service_id: str, billers_code: str, meter_type: str | None, renewing: float | None) -> str:
    if billers_code in TRIGGERS:
        return TRIGGERS[billers_code]
    if service_id == "showmax":
        return (
            "success"
            if is_nigerian_mobile(billers_code) or billers_code == DOCUMENTED_SUCCESS_NUMBER
            else "failed"
        )
    if SERVICES[service_id][0] == "electricity":
        return "success" if METERS.get(billers_code) == meter_type else "failed"
    wrong_renewal = renewing is not None and renewing != TV_ACCOUNTS[service_id].get("Renewal_Amount")
    return "success" if billers_code == SMARTCARD and not wrong_renewal else "failed"


def parse_order(body: dict[str, Any], now: int) -> SimOrder | dict[str, str]:
    """The order a `pay` request for a bill makes, or the reply that refuses it (code 011, as VTpass does)."""
    text = {
        k: str(body.get(k) or "")
        for k in ("request_id", "serviceID", "billersCode", "phone", "variation_code", "subscription_type")
    }
    try:
        amount = float(body["amount"]) if body.get("amount") not in (None, "") else None
    except TypeError, ValueError:
        amount = None
    service_id, kind = text["serviceID"], SERVICES[text["serviceID"]][0]
    missing = not all(text[k] for k in ("request_id", "billersCode", "phone"))
    no_money = amount is None and not (kind == "tv" and text["variation_code"])
    no_type = kind == "electricity" and text["variation_code"] not in HOLDERS
    if missing or no_money or no_type or (service_id in ("dstv", "gotv") and not _tv_choice_is_clear(text)):
        return {"code": "011", "response_description": "INVALID ARGUMENTS"}
    renewing = amount if text["subscription_type"] == RENEWAL else None
    meter_type = text["variation_code"] if kind == "electricity" else None
    scenario = _scenario(service_id, text["billersCode"], meter_type, renewing)
    return SimOrder(
        text["request_id"],
        service_id,
        text["phone"],
        amount or 0.0,
        text["variation_code"] or None,
        scenario,
        now,
        billers_code=text["billersCode"],
        subscription_type=text["subscription_type"] or None,
    )


def _tv_choice_is_clear(text: dict[str, str]) -> bool:
    """DStv and GOtv take a bouquet to change to, or a renewal without one."""
    if text["subscription_type"] == "change":
        return bool(text["variation_code"])
    return text["subscription_type"] == RENEWAL and not text["variation_code"]


def _digits(request_id: str, length: int) -> str:
    return str(int(hashlib.sha256(request_id.encode()).hexdigest(), 16))[:length]


def delivered_fields(order: SimOrder) -> dict[str, Any]:
    """What a delivered bill adds to the reply beside the transaction: a token, units and a tariff for a
    prepaid meter, the balance of a postpaid one, a Showmax voucher."""
    kind = SERVICES[order.service_id][0]
    if order.service_id == "showmax":
        return {"Voucher": f"SMX-{_digits(order.request_id, 4)}-{_digits(order.request_id[::-1], 4)}"}
    if kind == "tv":
        return {"purchased_code": ""}
    reference = f"SIM{_digits(order.request_id, 12)}"
    if order.variation_code == "postpaid":
        return {
            "purchased_code": "",
            "customerName": HOLDERS["postpaid"],
            "customerAddress": ADDRESSES["postpaid"],
            "meterNumber": None,
            "utilityName": SERVICES[order.service_id][1],
            "exchangeReference": reference,
            "balance": 0,
        }
    token = f"Token : {_digits(order.request_id, 20)}"
    units = round(order.amount_naira / KWH_PRICE_NAIRA, 1)
    return {
        "purchased_code": token,
        "token": token,
        "tokenAmount": order.amount_naira,
        "units": f"{units} kWh",
        "tariff": "R2 residential, N70 per kWh",
        "exchangeReference": reference,
    }
