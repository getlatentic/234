# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading an authorization request. A bad client or redirect URI is shown to the person (never redirected
to); anything else wrong is sent back to the client's redirect URI as an OAuth error."""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from .clients import Fetch, InvalidClient, resolve
from .grants import CHALLENGE
from .models import Client
from .redirects import matches
from .resources import connector_of, issuer, resource_url, scope_of, what_it_can_do

MAX_STATE = 500


class Unsafe(Exception):
    """The request names no client or redirect URI to trust: the person is told, and nothing is sent."""


@dataclass
class Refused(Exception):
    """An OAuth error for the client, sent to its redirect URI."""

    redirect_uri: str
    error: str
    description: str
    state: str | None


@dataclass(frozen=True)
class Authorization:
    client: Client
    redirect_uri: str
    state: str | None
    challenge: str
    connector: str
    scope: str

    @property
    def resource(self) -> str:
        return resource_url(self.connector)

    @property
    def what_it_can_do(self) -> str:
        return what_it_can_do(self.connector)

    @property
    def redirect_host(self) -> str:
        return urlsplit(self.redirect_uri).netloc

    @property
    def redirect_origin(self) -> str:
        parts = urlsplit(self.redirect_uri)
        return f"{parts.scheme}://{parts.netloc}"

    def fields(self) -> dict[str, str]:
        """The request as the consent form carries it back; the POST reads it again from the start."""
        found = {
            "response_type": "code",
            "client_id": self.client.client_id,
            "redirect_uri": self.redirect_uri,
            "code_challenge": self.challenge,
            "code_challenge_method": "S256",
            "resource": self.resource,
            "scope": self.scope,
        }
        return {**found, "state": self.state} if self.state is not None else found


def back_to_client(redirect_uri: str, state: str | None, **params: str) -> str:
    query = {**params, "iss": issuer(), **({"state": state} if state is not None else {})}
    joiner = "&" if urlsplit(redirect_uri).query else "?"
    return f"{redirect_uri}{joiner}{urlencode(query)}"


def _client(params: Mapping[str, str], fetch: Fetch) -> tuple[Client, str]:
    try:
        client = resolve(params.get("client_id"), fetch)
    except InvalidClient as refused:
        raise Unsafe(str(refused)) from refused
    redirect_uri = params.get("redirect_uri", "")
    if not matches(client.redirect_uris, redirect_uri):
        raise Unsafe("The redirect URI is not one this client registered.")
    return client, redirect_uri


def _scope(params: Mapping[str, str], connector: str) -> str | None:
    asked = params.get("scope")
    granted = scope_of(connector)
    return granted if asked is None or granted in asked.split() else None


def read(params: Mapping[str, str], fetch: Fetch) -> Authorization:
    client, redirect_uri = _client(params, fetch)
    state = params.get("state")
    if state is not None and len(state) > MAX_STATE:
        state = None

    def refuse(error: str, description: str) -> Refused:
        return Refused(redirect_uri, error, description, state)

    if params.get("response_type") != "code":
        raise refuse("unsupported_response_type", "Only the code flow is supported.")
    if params.get("code_challenge_method") != "S256" or not CHALLENGE.fullmatch(
        params.get("code_challenge", "")
    ):
        raise refuse("invalid_request", "PKCE with S256 is required.")
    connector = connector_of(params.get("resource", ""))
    if connector is None:
        raise refuse("invalid_target", "resource must name one of 234's MCP servers.")
    scope = _scope(params, connector)
    if scope is None:
        raise refuse("invalid_scope", f"This server needs the {scope_of(connector)} scope.")
    return Authorization(client, redirect_uri, state, params["code_challenge"], connector, scope)
