# SPDX-License-Identifier: AGPL-3.0-or-later
"""The personal agents this host accepts (PACT §3.1), registered by the owner in PACT_AGENTS: each one's
issuer and JWKS URL, and whether it is enabled. PACT_AUDIENCE is the one audience this host assigns them all.
Only listed agents are accepted (a trusted-issuer registry)."""

import json
from dataclasses import dataclass
from functools import cache
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from signatures.jwks import KeySet

from .transport import fetch


@dataclass(frozen=True)
class Agent:
    issuer: str
    jwks_uri: str
    enabled: bool = True


def _jwks_uri_ok(uri: str) -> bool:
    parts = urlsplit(uri)
    local = settings.DEBUG and parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost")
    return parts.scheme == "https" or local


@cache
def registry() -> dict[str, Agent]:
    try:
        listed = json.loads(settings.PACT_AGENTS or "[]")
        agents = {
            a["issuer"]: Agent(a["issuer"], a["jwks_uri"], bool(a.get("enabled", True))) for a in listed
        }
    except (ValueError, KeyError, TypeError) as error:
        raise ImproperlyConfigured("PACT_AGENTS is a JSON list of {issuer, jwks_uri, enabled}.") from error
    if not all(_jwks_uri_ok(a.jwks_uri) for a in agents.values()):
        raise ImproperlyConfigured("A personal agent's jwks_uri must be HTTPS.")
    return agents


@cache
def keys_of(issuer: str) -> KeySet:
    """One key cache per agent and isolate."""
    return KeySet(url=registry()[issuer].jwks_uri, fetch=fetch)
