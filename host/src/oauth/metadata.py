# SPDX-License-Identifier: AGPL-3.0-or-later
"""The two discovery documents: RFC 8414 authorization server metadata and RFC 9728 protected resource
metadata, one per connector."""

from typing import Any

from django.urls import reverse

from .resources import SCOPES, issuer, resource_url, scope_of


def authorization_server() -> dict[str, Any]:
    base = issuer()
    return {
        "issuer": base,
        "authorization_endpoint": base + reverse("oauth:authorize"),
        "token_endpoint": base + reverse("oauth:token"),
        "registration_endpoint": base + reverse("oauth:register"),
        "revocation_endpoint": base + reverse("oauth:revoke"),
        "scopes_supported": list(SCOPES),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "client_id_metadata_document_supported": True,
        "authorization_response_iss_parameter_supported": True,
    }


def protected_resource(connector: str) -> dict[str, Any]:
    return {
        "resource": resource_url(connector),
        "authorization_servers": [issuer()],
        "scopes_supported": [scope_of(connector)],
        "bearer_methods_supported": ["header"],
        "resource_name": f"234 {connector}",
    }
