# SPDX-License-Identifier: AGPL-3.0-or-later
"""The plans the simulated VTpass sells. MTN's are the ones in VTpass's documentation; the other
networks get labelled sample plans, and the television services plausible bouquets."""

from typing import Any

from ..network import NETWORK_LABEL
from .api import DATA_SERVICE

# Plausible bouquets and prices for the simulated television services: invented, near what they charge.
TV_BOUQUETS: dict[str, tuple[str, list[tuple[str, str, int]]]] = {
    "dstv": (
        "DStv Subscription",
        [
            ("dstv-padi", "DStv Padi", 4400),
            ("dstv-yanga", "DStv Yanga", 6000),
            ("dstv-confam", "DStv Confam", 10500),
            ("dstv-compact", "DStv Compact", 15700),
            ("dstv-compact-plus", "DStv Compact Plus", 25000),
            ("dstv-premium", "DStv Premium", 37000),
        ],
    ),
    "gotv": (
        "GOtv Payment",
        [
            ("gotv-smallie", "GOtv Smallie", 1900),
            ("gotv-jinja", "GOtv Jinja", 3900),
            ("gotv-jolli", "GOtv Jolli", 5800),
            ("gotv-max", "GOtv Max", 8500),
            ("gotv-supa", "GOtv Supa", 11400),
        ],
    ),
    "startimes": (
        "StarTimes Subscription",
        [
            ("nova", "Nova - 1 week", 600),
            ("basic", "Basic - 1 month", 3700),
            ("smart", "Smart - 1 month", 4700),
            ("classic", "Classic - 1 month", 5500),
            ("super", "Super - 1 month", 9000),
        ],
    ),
    "showmax": (
        "Showmax",
        [
            ("showmax-mobile", "Showmax Mobile - 1 month", 1450),
            ("showmax-standard", "Showmax Standard - 1 month", 3200),
            ("showmax-premier", "Showmax Premier League - 1 month", 6300),
        ],
    ),
}


def _plan(code: str, name: str, naira: int) -> dict[str, Any]:
    return {"variation_code": code, "name": name, "variation_amount": f"{naira:.2f}", "fixedPrice": "Yes"}


def simulated_variations(service_id: str) -> tuple[str, list[dict[str, Any]]] | None:
    """The service name and its plans, or None for a service this simulator does not know."""
    if service_id in TV_BOUQUETS:
        name, bouquets = TV_BOUQUETS[service_id]
        return name, [_plan(code, label, naira) for code, label, naira in bouquets]
    network = next((n for n, service in DATA_SERVICE.items() if service == service_id), None)
    if network is None:
        return None
    if network == "mtn":
        return "MTN Data", [
            _plan("mtn-10mb-100", "N100 100MB - 24 hrs", 100),
            _plan("mtn-50mb-200", "N200 200MB - 2 days", 200),
            _plan("mtn-100mb-1000", "N1000 1.5GB - 30 days", 1000),
            _plan("mtn-20hrs-1500", "N1500 6GB - 7 days", 1500),
            _plan("mtn-500mb-2000", "N2000 4.5GB - 30 days", 2000),
            _plan("mtn-3gb-2500", "N2500 6GB - 30 days", 2500),
        ]
    label = NETWORK_LABEL[network]
    return f"{label} Data (simulated plans)", [
        _plan(f"{service_id}-1gb-300", f"N300 1GB - 7 days (simulated {label} plan)", 300),
        _plan(f"{service_id}-3gb-1000", f"N1000 3GB - 30 days (simulated {label} plan)", 1000),
        _plan(f"{service_id}-10gb-3000", f"N3000 10GB - 30 days (simulated {label} plan)", 3000),
    ]
