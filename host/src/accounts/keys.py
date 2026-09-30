# SPDX-License-Identifier: AGPL-3.0-or-later
"""Google's public keys for Firebase ID tokens, fetched and kept as long as Google says they may be.

The keys are the JSON Web Key form of the certificates at
https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com (the same keys, the
same `kid`s, the modulus and exponent ready to use, so no certificate has to be parsed). The cache honours
`Cache-Control: max-age`. A token naming a `kid` that is not cached makes one refetch, and never more than one
in `REFETCH_SECONDS`, so a caller cannot turn random key ids into a stream of requests to Google.
"""

import base64
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

GOOGLE_KEYS_URL = "https://www.googleapis.com/robot/v1/metadata/jwk/securetoken@system.gserviceaccount.com"
DEFAULT_TTL = 3600
MIN_TTL, MAX_TTL = 60, 24 * 3600
REFETCH_SECONDS = 60

Fetch = Callable[[str], tuple[int, dict[str, str], bytes]]
PublicKey = tuple[int, int]


class KeysUnavailable(Exception):
    """Google's keys could not be fetched or read."""


def _integer(encoded: str) -> int:
    return int.from_bytes(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)), "big")


def _max_age(headers: dict[str, str]) -> int:
    found = re.search(r"max-age=(\d+)", {k.lower(): v for k, v in headers.items()}.get("cache-control", ""))
    return min(MAX_TTL, max(MIN_TTL, int(found[1]))) if found else DEFAULT_TTL


def parse(body: bytes) -> dict[str, PublicKey]:
    try:
        listed = json.loads(body)["keys"]
        return {
            k["kid"]: (_integer(k["n"]), _integer(k["e"]))
            for k in listed
            if k.get("kty") == "RSA" and k.get("alg", "RS256") == "RS256" and isinstance(k.get("kid"), str)
        }
    except (ValueError, KeyError, TypeError) as error:
        raise KeysUnavailable("Google's key document could not be read.") from error


@dataclass
class GoogleKeys:
    fetch: Fetch
    url: str = GOOGLE_KEYS_URL
    clock: Callable[[], float] = time.time
    _keys: dict[str, PublicKey] = field(default_factory=dict)
    _expires: float = 0.0
    _fetched: float = float("-inf")

    def _load(self) -> None:
        status, headers, body = self.fetch(self.url)
        if status != 200:
            raise KeysUnavailable(f"Google's keys answered {status}.")
        self._keys = parse(body)
        self._fetched = self.clock()
        self._expires = self._fetched + _max_age(headers)

    def get(self, kid: str) -> PublicKey | None:
        if self.clock() >= self._expires:
            self._load()
        found = self._keys.get(kid)
        if found is None and self.clock() - self._fetched >= REFETCH_SECONDS:
            self._load()
            found = self._keys.get(kid)
        return found
