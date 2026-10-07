# SPDX-License-Identifier: AGPL-3.0-or-later
"""A personal agent's public keys, fetched from its JWKS and kept as long as its Cache-Control says (one
minute to a day). A token naming a key id that is not cached makes one refetch, never more than one every ten
seconds per agent: a rotated key is honoured within seconds, and random key ids cannot become a stream of
requests to the agent."""

import base64
import json
import re
import time
from collections.abc import Awaitable, Callable
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
class _Cached:
    """The keys of one JWKS and when to read it again: when its cache life ends, or for a key id it lacks,
    once the cooldown since the last read has passed."""

    clock: Callable[[], float] = time.time
    _keys: dict[str, Key] = field(default_factory=dict)
    _expires: float = 0.0
    _fetched: float = float("-inf")

    def _stale(self) -> bool:
        return self.clock() >= self._expires

    def _worth_refetch(self, kid: str) -> bool:
        return kid not in self._keys and self.clock() - self._fetched >= REFETCH_SECONDS

    def _keep(self, status: int, headers: dict[str, str], body: bytes) -> None:
        if status != 200:
            raise KeysUnavailable(f"The JWKS answered {status}.")
        self._keys = parse(body)
        self._fetched = self.clock()
        self._expires = self._fetched + _max_age(headers)


@dataclass
class KeySet(_Cached):
    url: str = ""
    fetch: Fetch | None = None

    def _load(self) -> None:
        assert self.fetch is not None
        self._keep(*self.fetch(self.url))

    def get(self, kid: str) -> Key | None:
        if self._stale():
            self._load()
        if self._worth_refetch(kid):
            self._load()
        return self._keys.get(kid)


AsyncFetch = Callable[[str], Awaitable[tuple[int, dict[str, str], bytes]]]


@dataclass
class AsyncKeySet(_Cached):
    """The same cache for a caller that fetches asynchronously (the turn runner)."""

    url: str = ""
    fetch: AsyncFetch | None = None

    async def _load(self) -> None:
        assert self.fetch is not None
        self._keep(*(await self.fetch(self.url)))

    async def get(self, kid: str) -> Key | None:
        if self._stale():
            await self._load()
        if self._worth_refetch(kid):
            await self._load()
        return self._keys.get(kid)
