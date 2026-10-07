# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Brand's receipt checked as PACT's own client checks it (§5.6): signed by a key in the JWKS the Brand's
authorization server metadata names, the signed payload the same as the claims shown, and naming 234 as the
agent and this Brand's interface. A receipt that fails any of these is not kept, and the person is told."""

from collections.abc import Callable
from typing import Any

import httpx

from signatures import jws
from signatures.jwks import AsyncKeySet, KeysUnavailable

from .directory import Brand
from .wire import BrandUnavailable, json_of

CLAIMS = ("grantId", "user", "pa", "brand", "scopesUsed", "actions", "ts")


class ReceiptRefused(Exception):
    """The receipt does not hold."""


class Receipts:
    def __init__(self, client: httpx.AsyncClient, clock: Callable[[], float]) -> None:
        self._client, self._clock = client, clock
        self._jwks_uri: dict[str, str] = {}
        self._keys: dict[str, AsyncKeySet] = {}

    async def _fetch(self, url: str) -> tuple[int, dict[str, str], bytes]:
        try:
            answer = await self._client.get(url, headers={"accept": "application/json"})
        except httpx.HTTPError as error:
            raise KeysUnavailable(f"{url} could not be reached.") from error
        return answer.status_code, dict(answer.headers), answer.content

    async def _key_set(self, brand: Brand) -> AsyncKeySet:
        metadata_url = brand.delegation.metadata_url if brand.delegation else ""
        if not metadata_url:
            raise ReceiptRefused("The Brand publishes no keys.")
        if metadata_url not in self._jwks_uri:
            uri = (await json_of(self._client, metadata_url)).get("jwks_uri")
            if not isinstance(uri, str) or not uri:
                raise ReceiptRefused("The Brand's metadata names no keys.")
            self._jwks_uri[metadata_url] = uri
        uri = self._jwks_uri[metadata_url]
        if uri not in self._keys:
            self._keys[uri] = AsyncKeySet(url=uri, fetch=self._fetch, clock=self._clock)
        return self._keys[uri]

    async def verified(self, receipt: dict[str, Any], brand: Brand, issuer: str) -> dict[str, Any]:
        found = jws.parts(str(receipt.get("jws", "")))
        if found is None or not isinstance(found.header.get("kid"), str):
            raise ReceiptRefused("The receipt is not a signed JWS.")
        try:
            key = await (await self._key_set(brand)).get(found.header["kid"])
        except (KeysUnavailable, BrandUnavailable) as error:
            raise ReceiptRefused(f"The Brand's keys could not be read: {error}") from error
        if key is None or not jws.signed_by(found, key):
            raise ReceiptRefused("The receipt's signature does not verify.")
        claims = found.claims
        if claims != receipt.get("claims") or not all(name in claims for name in CLAIMS):
            raise ReceiptRefused("The receipt's claims are not the ones signed.")
        if claims["pa"] != issuer or claims["brand"] != brand.interface_url:
            raise ReceiptRefused("The receipt is for another agent or Brand.")
        return claims
