# SPDX-License-Identifier: AGPL-3.0-or-later
"""The account check of a television or electricity merchant: VTpass's `merchant-verify` for a smartcard or a
meter, read into what the core keeps (commerce/checks.py). The holder's name is the person's confirmation
that the number is right. What else VTpass gave (the address, the current bouquet, the arrears, a due date)
is shown on the card and in the reply; what a quote prices from (the renewal amount, the meter's least and
most) is kept as JSON values in the check's `detail`. Anything VTpass left out is left out here."""

from collections.abc import Mapping

from ..errors import DomainError
from ..money import format_naira
from ..vtpass.api import VtpassApi, VtpassError
from ..vtpass.bills import SERVICES, BillAccount, BillCheck, BillRefused
from .model import Merchant
from .provider import AccountLookup
from .text import third_party

FACT_LIMIT = 80
ACCOUNT_FIELD = {"tv": "smartcard", "electricity": "meter_number"}
METER_TYPE = "meter_type"
RENEW_NEXT = (
    "To renew the bouquet it has, quote the offer renew with no amount_kobo; if the person named another "
    "bouquet, quote that bouquet's offer_id instead."
)


def _date(value: str) -> str:
    return value.split("T")[0]


def _facts(account: BillAccount) -> list[list[str]]:
    shown = (
        ("Address", account.address),
        ("Meter type", account.meter_type.lower() if account.meter_type else None),
        ("Account type", account.account_type),
        ("Status", account.status),
        ("Current bouquet", account.bouquet),
        ("Renewal amount", format_naira(account.renewal_kobo) if account.renewal_kobo else None),
        ("Due date", _date(account.due_date) if account.due_date else None),
        ("Arrears", format_naira(account.arrears_kobo) if account.arrears_kobo else None),
        ("Least purchase", format_naira(account.min_kobo) if account.min_kobo else None),
        ("Most purchase", format_naira(account.max_kobo) if account.max_kobo else None),
    )
    return [[label, third_party(value, FACT_LIMIT)] for label, value in shown if value]


def lookup_of(account: BillAccount) -> AccountLookup:
    """What the core keeps of an account: the holder, what is owed, the facts, the amounts to price from."""
    priced = {
        "renewal_kobo": account.renewal_kobo,
        "min_kobo": account.min_kobo,
        "max_kobo": account.max_kobo,
        "bouquet": third_party(account.bouquet, FACT_LIMIT) if account.bouquet else None,
    }
    detail = {"facts": _facts(account), **{k: v for k, v in priced.items() if v is not None}}
    if account.renewal_kobo:
        detail["next"] = RENEW_NEXT
    return AccountLookup(account.holder, account.arrears_kobo or None, detail)


async def verify(api: VtpassApi, merchant: Merchant, fields: Mapping[str, str]) -> AccountLookup:
    """Looks the smartcard or meter up, or raises why it was not found. A refused one is never quoted."""
    kind = SERVICES[merchant.id][0]
    check = BillCheck(merchant.id, fields[ACCOUNT_FIELD[kind]], fields.get(METER_TYPE))
    try:
        account = await api.verify_bill(check)
    except BillRefused as error:
        raise DomainError(
            "ACCOUNT_NOT_FOUND",
            f"{merchant.name}: {error} Nothing was quoted. Ask the person to check the number"
            f"{' and whether the meter is prepaid or postpaid' if kind == 'electricity' else ''}.",
        ) from error
    except VtpassError as error:
        raise DomainError("PROVIDER_ERROR", f"VTpass could not check the account: {error}") from error
    return lookup_of(account)
