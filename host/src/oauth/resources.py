# SPDX-License-Identifier: AGPL-3.0-or-later
"""The protected resources: one MCP endpoint per connector, at /mcp/<connector>, each with its scope."""

from django.conf import settings

from turns.hub import MEMORY_SERVER

MONEY_SCOPE = "payments"
MEMORY_SCOPE = "memory"
SCOPES = (MONEY_SCOPE, MEMORY_SCOPE)
WHAT_IT_CAN_DO = {
    "paystack-pay": "It can make payment quotes for merchants. You approve every payment.",
    "send-money": "It can make bank transfer quotes. You approve every transfer.",
    "airtime": "It can make airtime and data quotes. You approve every purchase.",
    "food-order": "It can show menus and make food order quotes. You approve every order.",
    MEMORY_SERVER: "It can read and change what 234 remembers for you.",
}


def connectors() -> tuple[str, ...]:
    return tuple(settings.CONNECTORS)


def scope_of(connector: str) -> str:
    return MEMORY_SCOPE if connector == MEMORY_SERVER else MONEY_SCOPE


def what_it_can_do(connector: str) -> str:
    return WHAT_IT_CAN_DO.get(connector, "It can use this 234 service for you. You approve every payment.")


def resource_url(connector: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/mcp/{connector}"


def metadata_url(connector: str) -> str:
    return f"{settings.PUBLIC_BASE_URL}/.well-known/oauth-protected-resource/mcp/{connector}"


def connector_of(resource: str) -> str | None:
    """The connector a `resource` parameter names, compared without a trailing slash and with the scheme and
    host in any case (RFC 8707 canonical form)."""
    given = resource.rstrip("/")
    scheme, sep, rest = given.partition("://")
    host, slash, path = rest.partition("/")
    canonical = f"{scheme.lower()}{sep}{host.lower()}{slash}{path}"
    return next((c for c in connectors() if resource_url(c) == canonical), None)


def issuer() -> str:
    return settings.PUBLIC_BASE_URL
