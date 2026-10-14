# SPDX-License-Identifier: AGPL-3.0-or-later
"""An Index merchant as 234's `Merchant`: our own id (`index:<Index's id>`), our own words on when to choose
it, the fields its purchase needs, and limits that are Index's bounds under 234's caps. Whether the person
must connect first depends on who is asking: everything needs their Index account, and Chowdeck also needs it
linked."""

from ...money import format_naira
from ..model import FieldSpec, Merchant
from .bounds import limits_for
from .catalog import Entry
from .naming import our_id
from .settings import IndexSettings

AIRTIME_FIELDS = (FieldSpec("phone", "Phone number to top up", "text", most=20),)
ELECTRICITY_FIELDS = (
    FieldSpec("meter_type", "Meter type", "choice", options=("prepaid", "postpaid")),
    FieldSpec("meter_number", "Meter number", "digits", least=6, most=20),
)
FOOD_FIELDS = (
    FieldSpec(
        "delivery_to",
        "Saved address to deliver to (home, office or an area), if not their main one",
        "text",
        required=False,
        most=60,
    ),
)
FIELDS = {"airtime": AIRTIME_FIELDS, "electricity": ELECTRICITY_FIELDS, "food": FOOD_FIELDS}
FEE_LABEL = "Fee"
USE_INDEX = "Only when the person asks to use Index"


def blurb_of(entry: Entry, settings: IndexSettings) -> str:
    least, most = limits_for(entry.kind, settings)
    bounds = f"{format_naira(least)} to {format_naira(most)}"
    match entry.kind:
        case "food":
            return (
                "Chowdeck food delivery through the person's own Paystack Index account, one restaurant per "
                f"order, {bounds}. Only when the person asks for Chowdeck or Index."
            )
        case "airtime":
            return (
                f"{entry.code} airtime through the person's own Paystack Index account, paid from their Zap, "
                f"{bounds}. {USE_INDEX}; 234's own airtime is the default."
            )
        case _:
            return (
                f"Electricity for {entry.name} through the person's own Paystack Index account, paid from their "
                f"Zap, {bounds}; the meter is checked first. {USE_INDEX}."
            )


def merchant_of(entry: Entry, connected: bool, linked: frozenset[str], settings: IndexSettings) -> Merchant:
    least, most = limits_for(entry.kind, settings)
    needs_link = not connected or (entry.asks_link and entry.index_id not in linked)
    return Merchant(
        id=our_id(entry.index_id),
        provider="index",
        name=entry.name,
        category=entry.kind,
        status=entry.status,
        requires_link=needs_link,
        blurb=blurb_of(entry, settings),
        min_kobo=least,
        max_kobo=most,
        fee_label=FEE_LABEL,
        fee_kobo=0,
        checks_account=entry.kind == "electricity",
        fields=FIELDS[entry.kind],
    )
