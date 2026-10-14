# SPDX-License-Identifier: AGPL-3.0-or-later
"""Index's OAuth 2.1 server from 234's side: its metadata, a client registered once (RFC 7591), the
authorization-code grant with PKCE S256 (the person signs in at Index and Index sends the browser back with a
code), the refresh grant, the client-credentials grant (for the public directory only), and revocation
(RFC 7009) where Index's metadata names an endpoint. Every endpoint the metadata names must be on a host the
deployment trusts, so a poisoned document cannot send a token elsewhere."""

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

from ...clock import Clock
from ...transport import Reply, Transport, TransportError
from .wire import USER_AGENT, IndexMisread, IndexProblem, IndexRefused, IndexUnreachable

SCOPE = "mcp:transact"
METADATA_PATH = "/.well-known/oauth-authorization-server"
METADATA_TTL_MS = 60 * 60_000
CLIENT_NAME = "234"
TIMEOUT_SECONDS = 20.0


class TokenRefused(IndexProblem):
    """The token endpoint said no: the grant is not honoured (`invalid_grant`), or the client is not."""

    def __init__(self, code: str, description: str = "") -> None:
        super().__init__(f"{code}: {description}" if description else code)
        self.code = code


@dataclass(frozen=True)
class Endpoints:
    authorization: str
    token: str
    registration: str
    revocation: str | None


@dataclass(frozen=True)
class Registration:
    client_id: str
    secret: str | None
    auth_method: str


@dataclass(frozen=True)
class Tokens:
    access: str
    refresh: str | None
    expires_at: int
    """Milliseconds since the epoch."""
    scope: str


def challenge_of(verifier: str) -> str:
    """The S256 code challenge of a PKCE verifier (RFC 7636)."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def json_of(reply: Reply) -> dict[str, Any]:
    try:
        parsed = json.loads(reply.body)
    except ValueError:
        parsed = None
    return parsed if isinstance(parsed, dict) else {}


class IndexOAuth:
    def __init__(
        self, transport: Transport, metadata_url: str, trusted: frozenset[str], clock: Clock
    ) -> None:
        """`trusted`: the origins an endpoint named by the metadata may have."""
        self._transport, self._clock, self._trusted = transport, clock, trusted
        self._metadata_url = metadata_url
        self._known: tuple[int, Endpoints] | None = None

    async def _send(self, method: str, url: str, headers: Mapping[str, str], body: str | None) -> Reply:
        try:
            return await self._transport.send(
                method,
                url,
                headers={"user-agent": USER_AGENT, "accept": "application/json", **headers},
                body=body,
                timeout_seconds=TIMEOUT_SECONDS,
            )
        except TransportError as error:
            raise IndexUnreachable(str(error)) from error

    async def endpoints(self) -> Endpoints:
        now = self._clock.now()
        if self._known and now - self._known[0] < METADATA_TTL_MS:
            return self._known[1]
        reply = await self._send("GET", self._metadata_url, {}, None)
        if reply.status >= 500:
            raise IndexUnreachable(f"Index's metadata answered {reply.status}.")
        found = json_of(reply)
        endpoints = Endpoints(
            self._trusted_url(found.get("authorization_endpoint")),
            self._trusted_url(found.get("token_endpoint")),
            self._trusted_url(found.get("registration_endpoint")),
            self._trusted_url(found["revocation_endpoint"]) if found.get("revocation_endpoint") else None,
        )
        self._known = (now, endpoints)
        return endpoints

    def _trusted_url(self, url: object) -> str:
        if not isinstance(url, str) or origin_of(url) not in self._trusted:
            raise IndexMisread("Index's metadata names an address 234 does not send tokens to.")
        return url

    async def register(self, redirect_uri: str) -> Registration:
        endpoints = await self.endpoints()
        body = {
            "client_name": CLIENT_NAME,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
            "scope": SCOPE,
        }
        reply = await self._send(
            "POST", endpoints.registration, {"content-type": "application/json"}, json.dumps(body)
        )
        found = json_of(reply)
        if reply.status >= 500:
            raise IndexUnreachable(f"Index's registration answered {reply.status}.")
        if not reply.ok or not isinstance(found.get("client_id"), str):
            raise IndexRefused("Index did not register 234 as a client.")
        secret = found.get("client_secret") if isinstance(found.get("client_secret"), str) else None
        method = str(found.get("token_endpoint_auth_method") or ("client_secret_post" if secret else "none"))
        return Registration(found["client_id"], secret, method if secret else "none")

    async def authorize_url(
        self, registration: Registration, redirect_uri: str, state: str, challenge: str
    ) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": registration.client_id,
                "redirect_uri": redirect_uri,
                "scope": SCOPE,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{(await self.endpoints()).authorization}?{query}"

    def _client_auth(self, registration: Registration) -> tuple[dict[str, str], dict[str, str]]:
        """The headers and the form fields that identify the client at the token endpoint."""
        if registration.auth_method == "client_secret_basic" and registration.secret:
            pair = f"{registration.client_id}:{registration.secret}".encode()
            return {"authorization": f"Basic {base64.b64encode(pair).decode()}"}, {}
        fields = {"client_id": registration.client_id}
        if registration.auth_method == "client_secret_post" and registration.secret:
            fields["client_secret"] = registration.secret
        return {}, fields

    async def _token(self, registration: Registration, grant: dict[str, str]) -> Tokens:
        endpoints = await self.endpoints()
        headers, fields = self._client_auth(registration)
        reply = await self._send(
            "POST",
            endpoints.token,
            {"content-type": "application/x-www-form-urlencoded", **headers},
            urlencode({**grant, **fields}),
        )
        found = json_of(reply)
        if reply.status >= 500:
            raise IndexUnreachable(f"Index's token endpoint answered {reply.status}.")
        if not reply.ok or not isinstance(found.get("access_token"), str):
            raise TokenRefused(
                str(found.get("error") or reply.status), str(found.get("error_description", ""))
            )
        lifetime = found.get("expires_in")
        seconds = lifetime if isinstance(lifetime, int) and lifetime > 0 else 3600
        refresh = found.get("refresh_token")
        return Tokens(
            found["access_token"],
            refresh if isinstance(refresh, str) and refresh else None,
            self._clock.now() + seconds * 1000,
            str(found.get("scope") or SCOPE),
        )

    async def exchange(
        self, registration: Registration, redirect_uri: str, code: str, verifier: str
    ) -> Tokens:
        grant = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
        return await self._token(registration, grant)

    async def refresh(self, registration: Registration, refresh_token: str) -> Tokens:
        return await self._token(
            registration, {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    async def client_credentials(self, registration: Registration) -> Tokens:
        return await self._token(registration, {"grant_type": "client_credentials", "scope": SCOPE})

    async def revoke(self, registration: Registration, token: str, hint: str) -> bool:
        """Whether Index confirmed it revoked `token`; false when it offers no revocation."""
        revocation = (await self.endpoints()).revocation
        if revocation is None:
            return False
        headers, fields = self._client_auth(registration)
        reply = await self._send(
            "POST",
            revocation,
            {"content-type": "application/x-www-form-urlencoded", **headers},
            urlencode({"token": token, "token_type_hint": hint, **fields}),
        )
        return reply.status == 200
