# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Brands 234 may reach, as their Agent Cards describe them (PACT §2.1, §5.1): a name, what they do, the
interface 234 sends to, and whether and how a person can let 234 act on their account there. Cards are read
again after five minutes; a Brand whose card cannot be read is left out until it can."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Reached

CARD_SECONDS = 300
MAX_CARD_BYTES = 64 * 1024


@dataclass(frozen=True)
class Delegable:
    device_authorization_url: str
    token_url: str
    refresh_url: str
    metadata_url: str
    scopes: dict[str, str]


@dataclass(frozen=True)
class Brand:
    id: str
    name: str
    description: str
    skills: tuple[str, ...]
    interface_url: str
    reached: Reached
    delegation: Delegable | None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "brand"


def _interface(card: dict[str, Any]) -> str | None:
    for entry in card.get("supportedInterfaces") or []:
        if entry.get("protocolBinding") == "HTTP+JSON" and entry.get("protocolVersion") == "1.0":
            return str(entry.get("url", "")).rstrip("/") or None
    return None


def _is_bearer(scheme: dict[str, Any]) -> bool:
    http = scheme.get("httpAuthSecurityScheme") or {}
    return str(http.get("scheme", "")).lower() == "bearer"


def _device_code(scheme: dict[str, Any]) -> Delegable | None:
    oauth = scheme.get("oauth2SecurityScheme") or {}
    flow = (oauth.get("flows") or {}).get("deviceCode") or {}
    urls = (flow.get("deviceAuthorizationUrl"), flow.get("tokenUrl"), oauth.get("oauth2MetadataUrl"))
    if not all(isinstance(u, str) and u for u in urls) or not isinstance(flow.get("scopes"), dict):
        return None
    scopes = {str(k): str(v) for k, v in flow["scopes"].items()}
    return Delegable(urls[0], urls[1], str(flow.get("refreshUrl") or urls[1]), urls[2], scopes)


def delegation_of(card: dict[str, Any]) -> Delegable | None:
    """The device-code scheme a requirement names next to a Bearer JWT, as PACT's own client finds it."""
    schemes = card.get("securitySchemes") or {}
    for requirement in card.get("securityRequirements") or []:
        named = [schemes.get(name) or {} for name in (requirement.get("schemes") or {})]
        if len(named) != 2 or not any(_is_bearer(s) for s in named):
            continue
        for scheme in named:
            if found := _device_code(scheme):
                return found
    return None


def brand_of(card: dict[str, Any], reached: Reached, taken: set[str]) -> Brand | None:
    interface, name = _interface(card), str(card.get("name") or "").strip()
    if not interface or not name:
        return None
    slug, n = _slug(name), 2
    while slug in taken:
        slug, n = f"{_slug(name)}-{n}", n + 1
    skills = tuple(str(s.get("name") or s.get("id")) for s in card.get("skills") or [] if isinstance(s, dict))
    return Brand(
        slug, name, str(card.get("description") or ""), skills, interface, reached, delegation_of(card)
    )


class Directory:
    def __init__(self, reached: tuple[Reached, ...], client: httpx.AsyncClient, clock: Callable[[], float]):
        self._reached, self._client, self._clock = reached, client, clock
        self._brands: list[Brand] = []
        self._read_at = float("-inf")

    async def _card(self, reached: Reached) -> dict[str, Any] | None:
        try:
            answer = await self._client.get(reached.card_url, headers={"accept": "application/json"})
        except httpx.HTTPError:
            return None
        if answer.status_code != 200 or len(answer.content) > MAX_CARD_BYTES:
            return None
        try:
            card = answer.json()
        except ValueError:
            return None
        return card if isinstance(card, dict) else None

    async def brands(self) -> list[Brand]:
        if self._clock() - self._read_at < CARD_SECONDS and self._brands:
            return self._brands
        found: list[Brand] = []
        for reached in self._reached:
            card = await self._card(reached)
            brand = brand_of(card, reached, {b.id for b in found}) if card else None
            if brand:
                found.append(brand)
        self._brands, self._read_at = found, self._clock()
        return found

    async def find(self, brand_id: str) -> Brand | None:
        return next((b for b in await self.brands() if b.id == brand_id), None)
