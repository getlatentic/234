# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where a Brand's PACT endpoints are (§2.1, §5.1): its interface, and under it the authorization server
that issues its delegation tokens."""

from django.conf import settings

from .brands import Brand


def interface_url(brand: Brand) -> str:
    return f"{settings.PUBLIC_BASE_URL}/a2a/{brand.id}"


def issuer(brand: Brand) -> str:
    return f"{interface_url(brand)}/oauth"


def metadata_url(brand: Brand) -> str:
    return f"{issuer(brand)}/.well-known/oauth-authorization-server"


def device_authorization_url(brand: Brand) -> str:
    return f"{issuer(brand)}/device_authorization"


def token_url(brand: Brand) -> str:
    return f"{issuer(brand)}/token"


def jwks_url(brand: Brand) -> str:
    return f"{issuer(brand)}/jwks.json"


def verification_url(brand: Brand) -> str:
    """The page where the person signs in to 234 and decides."""
    return f"{issuer(brand)}/device"
