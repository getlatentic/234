# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which of Index's merchants 234 can buy from, and what each is called to Index. Index's directory names a
merchant by an id and a name; the network of an airtime merchant and the distribution company of an
electricity merchant are found in those, because the purchase tool wants them as codes. A merchant whose
network or company is not recognised is not offered: it cannot be bought from correctly."""

import re

PREFIX = "index:"
_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
NETWORKS = {"mtn": "MTN", "airtel": "AIRTEL", "glo": "GLO", "9mobile": "9MOBILE", "etisalat": "9MOBILE"}
DISCOS = {
    "ikeja": ("ikeja",),
    "eko": ("eko",),
    "phed": ("phed", "port harcourt", "portharcourt"),
    "kano": ("kano", "kedco"),
    "eedc": ("eedc", "enugu"),
    "aedc": ("aedc", "abuja"),
    "ibedc": ("ibedc", "ibadan"),
    "benin": ("benin", "behdc"),
    "abapower": ("abapower", "aba power"),
    "jos": ("jos", "jedc"),
    "kaduna": ("kaduna", "kaedco"),
    "yola": ("yola", "yedc"),
}
FOOD_MERCHANT = "chowdeck"


def our_id(index_id: str) -> str:
    return f"{PREFIX}{index_id}"


def index_id_of(merchant_id: str) -> str | None:
    """Index's id for one of our merchant ids, when it is one of Index's."""
    return merchant_id.removeprefix(PREFIX) if merchant_id.startswith(PREFIX) else None


def is_index_id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _words(index_id: str, name: str) -> str:
    return f"{index_id} {name}".lower().replace("-", " ").replace("_", " ")


def network_of(index_id: str, name: str) -> str | None:
    words = _words(index_id, name).split()
    return next((code for word, code in NETWORKS.items() if word in words), None)


def disco_of(index_id: str, name: str) -> str | None:
    text = _words(index_id, name)
    return next((code for code, names in DISCOS.items() if any(n in text for n in names)), None)


def kind_of(index_id: str, name: str, category: str) -> tuple[str, str | None] | None:
    """The kind of purchase (`food`, `airtime`, `electricity`) and the code Index wants for it (a network, a
    distribution company), or None for a merchant 234 does not buy from."""
    if index_id == FOOD_MERCHANT and category == "food":
        return "food", None
    if category == "airtime" and (network := network_of(index_id, name)):
        return "airtime", network
    if category in ("bills", "electricity") and (disco := disco_of(index_id, name)):
        return "electricity", disco
    return None
