# SPDX-License-Identifier: AGPL-3.0-or-later
"""The clients the authorization server knows: those that registered (RFC 7591), and those named by the URL of
a client ID metadata document, fetched and kept for a day."""

import json
import secrets
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from config.sql import returning

from .models import Client
from .redirects import acceptable

MAX_REDIRECTS = 10
MAX_NAME = 100
MAX_DOCUMENT_BYTES = 10_000
DOCUMENT_TTL = 24 * 3600

Fetch = Callable[[str], tuple[int, dict[str, str], bytes]]


class InvalidClient(Exception):
    """Client metadata that cannot be accepted; the message is safe to show the client."""

    def __init__(self, message: str, error: str = "invalid_client_metadata") -> None:
        super().__init__(message)
        self.error = error


def _name(metadata: dict[str, Any], fallback: str) -> str:
    name = metadata.get("client_name")
    if name is None:
        return fallback
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME:
        raise InvalidClient("client_name must be text of at most 100 characters.")
    return name.strip()


def _redirects(metadata: dict[str, Any]) -> list[str]:
    uris = metadata.get("redirect_uris")
    if not isinstance(uris, list) or not 1 <= len(uris) <= MAX_REDIRECTS:
        raise InvalidClient("redirect_uris must list 1 to 10 URIs.", "invalid_redirect_uri")
    if not all(acceptable(u) for u in uris):
        raise InvalidClient(
            "Each redirect URI must be HTTPS, or HTTP on localhost, with no fragment.", "invalid_redirect_uri"
        )
    return list(uris)


def _grants_ok(metadata: dict[str, Any]) -> None:
    """A client may list grants this server does not offer (Claude lists jwt-bearer); it is given only the
    code and refresh grants, and must be able to use the code grant."""
    grants = metadata.get("grant_types", ["authorization_code"])
    if not isinstance(grants, list) or "authorization_code" not in grants:
        raise InvalidClient("grant_types must include authorization_code.")
    responses = metadata.get("response_types", ["code"])
    if not isinstance(responses, list) or "code" not in responses:
        raise InvalidClient('response_types must include "code".')


def register(metadata: object, now: float | None = None) -> dict[str, Any]:
    """Registers a public client; any authentication method it asked for is answered with `none`."""
    if not isinstance(metadata, dict):
        raise InvalidClient("The body must be a JSON object.")
    uris = _redirects(metadata)
    _grants_ok(metadata)
    issued = int(now or time.time())
    client = Client.objects.create(
        client_id=f"234c_{secrets.token_urlsafe(18)}",
        name=_name(metadata, "An MCP client"),
        redirect_uris=uris,
        created_at=issued,
    )
    return {
        "client_id": client.client_id,
        "client_id_issued_at": issued,
        "client_name": client.name,
        "redirect_uris": uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


def is_document_url(client_id: str) -> bool:
    """A client ID metadata document is named by an HTTPS URL with a path, on a host name (not an address)."""
    parts = urlsplit(client_id)
    host = parts.hostname or ""
    return (
        parts.scheme == "https"
        and parts.path not in ("", "/")
        and not parts.fragment
        and "@" not in parts.netloc
        and "." in host
        and not host.replace(".", "").isdigit()
        and ":" not in host
    )


def _from_document(client_id: str, fetch: Fetch, now: int) -> Client:
    status, _, body = fetch(client_id)
    if status != 200 or len(body) > MAX_DOCUMENT_BYTES:
        raise InvalidClient("The client metadata document could not be fetched.")
    try:
        metadata = json.loads(body)
    except ValueError as error:
        raise InvalidClient("The client metadata document is not JSON.") from error
    if not isinstance(metadata, dict) or metadata.get("client_id") != client_id:
        raise InvalidClient("The client metadata document must name its own URL as client_id.")
    if metadata.get("token_endpoint_auth_method", "none") != "none":
        raise InvalidClient("Only public clients (token_endpoint_auth_method none) are supported.")
    uris = _redirects(metadata)
    _grants_ok(metadata)
    # One statement, whose rows say it ran: D1 refuses SELECT ... FOR UPDATE and miscounts updates (sql.py).
    returning(
        "INSERT INTO oauth_client (client_id, name, redirect_uris, fetched_at, created_at) "
        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (client_id) DO UPDATE SET name = excluded.name, "
        "redirect_uris = excluded.redirect_uris, fetched_at = excluded.fetched_at RETURNING client_id",
        [client_id, _name(metadata, urlsplit(client_id).hostname or client_id), json.dumps(uris), now, now],
    )
    return Client.objects.get(client_id=client_id)


def resolve(client_id: object, fetch: Fetch, now: float | None = None) -> Client:
    if not isinstance(client_id, str) or not client_id or len(client_id) > 512:
        raise InvalidClient("client_id is missing.")
    moment = int(now or time.time())
    known = Client.objects.filter(client_id=client_id).first()
    if not is_document_url(client_id):
        if known is None or known.fetched_at:
            raise InvalidClient("This client is not registered.")
        return known
    if known is not None and moment - known.fetched_at < DOCUMENT_TTL:
        return known
    return _from_document(client_id, fetch, moment)
