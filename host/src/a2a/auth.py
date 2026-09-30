# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who may call the A2A endpoint and from where: a bearer token per calling agent, the protocol version the
caller speaks, and a CORS allowlist. Nothing here trusts a browser cookie: another agent is not a visitor."""

import hmac
import re

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse

from .errors import Unauthenticated, VersionNotSupported

PRINCIPAL_PREFIX = "a:"
SUPPORTED_VERSION = "1.0"
ALLOWED_HEADERS = "authorization, content-type, a2a-version, a2a-extensions"
_MAJOR_MINOR = re.compile(r"^(\d+)\.(\d+)(?:\.\d+)?$")


def parse_tokens(raw: str) -> dict[str, str]:
    """`name:token,name:token` as name to token; a token is a secret, so a bad list stops the Worker."""
    tokens: dict[str, str] = {}
    for item in filter(None, (part.strip() for part in raw.split(","))):
        name, _, token = item.partition(":")
        if not name or len(token) < 16 or name in tokens:
            raise ImproperlyConfigured("A2A_TOKENS is name:token pairs, each token at least 16 characters.")
        tokens[name] = token
    return tokens


def principal_of(request: HttpRequest) -> str:
    given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    found = None
    for name, token in parse_tokens(settings.A2A_TOKENS).items():
        if hmac.compare_digest(given.encode(), token.encode()):
            found = name
    if not given or found is None:
        raise Unauthenticated("A bearer token is required.")
    return f"{PRINCIPAL_PREFIX}{found}"


def check_version(request: HttpRequest) -> None:
    """A caller that names no version is taken to speak 0.3, which this endpoint does not."""
    asked = request.headers.get("A2A-Version") or "0.3"
    found = _MAJOR_MINOR.match(asked)
    if found is None or f"{found[1]}.{found[2]}" != SUPPORTED_VERSION:
        raise VersionNotSupported(
            f"This agent speaks A2A {SUPPORTED_VERSION}; the request asked for {asked}."
        )


def add_cors(request: HttpRequest, response: HttpResponse) -> HttpResponse:
    origin = request.headers.get("Origin")
    if origin and origin in settings.A2A_CORS_ORIGINS:
        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Headers"] = ALLOWED_HEADERS
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response["Access-Control-Max-Age"] = "600"
    response["Vary"] = "Origin"
    return response
