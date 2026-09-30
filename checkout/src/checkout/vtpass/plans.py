# SPDX-License-Identifier: AGPL-3.0-or-later
"""The plans the simulated VTpass sells. MTN's are the ones in VTpass's documentation; the other
networks get labelled sample plans."""

from typing import Any

from ..network import NETWORK_LABEL
from .api import DATA_SERVICE


def _plan(code: str, name: str, naira: int) -> dict[str, Any]:
    return {"variation_code": code, "name": name, "variation_amount": f"{naira:.2f}", "fixedPrice": "Yes"}


def simulated_variations(service_id: str) -> tuple[str, list[dict[str, Any]]] | None:
    """The service name and its plans, or None for a service this simulator does not know."""
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
