# SPDX-License-Identifier: AGPL-3.0-or-later
"""The person letting 234 act on their account at a Brand (PACT §5.3, RFC 8628, from the agent's side): 234
asks the Brand for the scopes it needs and shows the person the Brand's own link; it asks the Brand's token
endpoint how that stands, never more often than the Brand's interval; and it refreshes a delegation before it
runs out, dropping it when the Brand no longer honours it."""

import secrets
from typing import Any

import httpx

from . import agent
from .config import ReachSettings
from .directory import Brand
from .store import Delegation, SignIn, Store
from .wire import BrandUnavailable, form

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
REFRESH_EARLY_SECONDS = 60
PENDING_ERRORS = ("authorization_pending", "slow_down")
ENDED = {"access_denied": "denied", "expired_token": "expired"}


class SigningIn:
    def __init__(self, settings: ReachSettings, store: Store, client: httpx.AsyncClient) -> None:
        self._settings, self._store, self._client = settings, store, client

    def _jwt(self, brand: Brand, owner: str, now: int) -> str:
        sub = agent.sub_for(owner, brand.reached.card_url)
        return agent.token(self._settings, brand.reached.audience, sub, now)

    async def _post(
        self, url: str, brand: Brand, owner: str, now: int, fields: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        jwt = self._jwt(brand, owner, now)
        return await form(self._client, url, jwt, {**fields, "client_id": self._settings.issuer})

    async def start(self, brand: Brand, owner: str, scopes: tuple[str, ...], now: int) -> SignIn:
        assert brand.delegation is not None
        wanted = tuple(s for s in scopes if s in brand.delegation.scopes)
        status, body = await self._post(
            brand.delegation.device_authorization_url, brand, owner, now, {"scope": " ".join(wanted)}
        )
        link = body.get("verification_uri_complete")
        if status != 200 or not isinstance(body.get("device_code"), str) or not isinstance(link, str):
            raise BrandUnavailable(f"The Brand did not start a sign-in ({body.get('error', status)}).")
        expires = now + int(body.get("expires_in") or 600)
        interval = max(int(body.get("interval") or 5), 1)
        sign_in = SignIn(
            f"si_{secrets.token_hex(12)}", owner, brand.id, body["device_code"], link, wanted, interval,
            expires, 0, "pending",
        )  # fmt: skip
        await self._store.start_sign_in(sign_in, now)
        return sign_in

    async def poll(self, sign_in: SignIn, brand: Brand, now_ms: int) -> tuple[str, bool]:
        """Where the sign-in stands now, and whether this call ended it; asks the Brand only once its
        interval has passed. Two cards asking at once settle it once: the first ending recorded stands."""
        now = now_ms // 1000
        if sign_in.state != "pending":
            return sign_in.state, False
        if now >= sign_in.expires_at:
            return await self._store.settle(sign_in.id, "expired")
        if now_ms - sign_in.polled_at < sign_in.interval * 1000 or brand.delegation is None:
            return "pending", False
        await self._store.polled(sign_in.id, now_ms)
        fields = {"grant_type": DEVICE_GRANT, "device_code": sign_in.device_code}
        status, body = await self._post(brand.delegation.token_url, brand, sign_in.owner, now, fields)
        if status == 200 and isinstance(body.get("access_token"), str):
            await self._store.keep_delegation(sign_in.owner, brand.id, _delegation(brand, body, now), now)
            return await self._store.settle(sign_in.id, "connected")
        error = str(body.get("error", ""))
        if error in PENDING_ERRORS:
            return "pending", False
        return await self._store.settle(sign_in.id, ENDED.get(error, "expired"))

    async def fresh(self, brand: Brand, owner: str, now: int) -> Delegation | None:
        """The person's delegation at this Brand, refreshed when it is about to run out; None when there is
        none or the Brand no longer honours it."""
        held = await self._store.delegation(owner, brand.id)
        if held is None or held.expires_at - REFRESH_EARLY_SECONDS > now:
            return held
        if not held.refresh_token or brand.delegation is None:
            await self._store.forget_delegation(owner, brand.id)
            return None
        fields = {"grant_type": "refresh_token", "refresh_token": held.refresh_token}
        status, body = await self._post(brand.delegation.refresh_url, brand, owner, now, fields)
        if status != 200 or not isinstance(body.get("access_token"), str):
            await self._store.forget_delegation(owner, brand.id)
            return None
        renewed = _delegation(brand, body, now)
        await self._store.keep_delegation(owner, brand.id, renewed, now)
        return renewed


def _delegation(brand: Brand, body: dict[str, Any], now: int) -> Delegation:
    scopes = tuple(str(body.get("scope", "")).split())
    expires = now + int(body.get("expires_in") or 3600)
    return Delegation(brand.name, body["access_token"], str(body.get("refresh_token") or ""), scopes, expires)
