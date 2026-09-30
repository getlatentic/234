# SPDX-License-Identifier: AGPL-3.0-or-later
"""The four Nigerian mobile networks the airtime connector sells for, and which number ranges each was
allocated."""

from typing import Literal

Network = Literal["mtn", "airtel", "glo", "9mobile"]

NETWORK_LABEL: dict[str, str] = {"mtn": "MTN", "airtel": "Airtel", "glo": "Glo", "9mobile": "9mobile"}

# NCC allocations by leading digits of a number in national form. A number moved to another network
# keeps its prefix, so this says where a number started, not where it is now.
NETWORK_PREFIXES: dict[Network, tuple[str, ...]] = {
    "mtn": (
        *("0703", "0704", "0706", "07025", "07026", "0803", "0806", "0810", "0813", "0814", "0816"),
        *("0903", "0906", "0913", "0916"),
    ),
    "airtel": ("0701", "0708", "0802", "0808", "0812", "0901", "0902", "0904", "0907", "0911", "0912"),
    "glo": ("0705", "0805", "0807", "0811", "0815", "0905", "0915"),
    "9mobile": ("0809", "0817", "0818", "0908", "0909"),
}


def network_of_number(phone: str) -> Network | None:
    """The network a number in national form (0803...) was allocated to, or None for a range this table
    does not list."""
    for network, prefixes in NETWORK_PREFIXES.items():
        if phone.startswith(prefixes):
            return network
    return None
