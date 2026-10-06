# SPDX-License-Identifier: AGPL-3.0-or-later
"""A personal agent's public keys, fetched from its JWKS and kept as long as its Cache-Control says (one
minute to a day). A token naming a key id that is not cached makes one refetch, never more than one every ten
seconds per agent: a rotated key is honoured within seconds, and random key ids cannot become a stream of
requests to the agent."""

import base64
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

Fetch = Callable[[str], tuple[int, dict[str, str], bytes]]
DEFAULT_TTL, MIN_TTL, MAX_TTL = 3600, 60, 24 * 3600
REFETCH_SECONDS = 10
MAX_DOCUMENT_BYTES = 64 * 1024


@dataclass(frozen=True)
class Key:
    """An RS256 key (`n`, `e`) or an ES256 key (`x`, `y` on P-256)."""

    alg: str
    a: int
    b: int


class KeysUnavailable(Exception):
    """The JWKS could not be fetched or read."""


def _integer(encoded: object) -> int:
    if not isinstance(encoded, str):
        raise ValueError("not a base64url string")
    return int.from_bytes(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)), "big")


def _key_of(entry: dict) -> Key | None:
    if entry.get("use", "sig") != "sig":
        return None
    if entry.get("kty") == "RSA" and entry.get("alg", "RS256") == "RS256":
        return Key("RS256", _integer(entry["n"]), _integer(entry["e"]))
    if entry.get("kty") == "EC" and entry.get("crv") == "P-256" and entry.get("alg", "ES256") == "ES256":
        return Key("ES256", _integer(entry["x"]), _integer(entry["y"]))
    return None


def parse(body: bytes) -> dict[str, Key]:
    if len(body) > MAX_DOCUMENT_BYTES:
        raise KeysUnavailable("The JWKS is too large.")
    try:
        listed = json.loads(body)["keys"]
        keys = {}
        for entry in listed:
            key = _key_of(entry) if isinstance(entry, dict) and isinstance(entry.get("kid"), str) else None
            if key is not None:
                keys[entry["kid"]] = key
        return keys
    except (ValueError, KeyError, TypeError) as error:
        raise KeysUnavailable("The JWKS could not be read.") from error


def _max_age(headers: dict[str, str]) -> int:
    found = re.search(r"max-age=(\d+)", {k.lower(): v for k, v in headers.items()}.get("cache-control", ""))
    return min(MAX_TTL, max(MIN_TTL, int(found[1]))) if found else DEFAULT_TTL


@dataclass
class KeySet:
    url: str
    fetch: Fetch
    clock: Callable[[], float] = time.time
    _keys: dict[str, Key] = field(default_factory=dict)
    _expires: float = 0.0
    _fetched: float = float("-inf")

    def _load(self) -> None:
        status, headers, body = self.fetch(self.url)
        if status != 200:
            raise KeysUnavailable(f"The JWKS answered {status}.")
        self._keys = parse(body)
        self._fetched = self.clock()
        self._expires = self._fetched + _max_age(headers)

    def get(self, kid: str) -> Key | None:
        if self.clock() >= self._expires:
            self._load()
        found = self._keys.get(kid)
        if found is None and self.clock() - self._fetched >= REFETCH_SECONDS:
            self._load()
            found = self._keys.get(kid)
        return found
