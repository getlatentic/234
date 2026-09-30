# SPDX-License-Identifier: AGPL-3.0-or-later
"""The card sandbox as this host runs it: where it is, what a card may declare, what the host tells a view."""

import hashlib
import hmac

from django.conf import settings

from config import runtime

from .card_csp import FIELDS, PERMISSIONS, OriginPolicy

PAYSTACK_INLINE = {
    "resourceDomains": ("https://js.paystack.co",),
    "frameDomains": ("https://checkout.paystack.com",),
}
MAX_HEIGHT = 6000


def origin_policy() -> OriginPolicy:
    allowed = {name: set(settings.CARD_ALLOWED_ORIGINS) for name in FIELDS}
    if settings.INLINE_PAYSTACK:
        for name, origins in PAYSTACK_INLINE.items():
            allowed[name].update(origins)
    return OriginPolicy(
        {name: frozenset(origins) for name, origins in allowed.items()},
        {server: frozenset({"resourceDomains"}) for server in settings.CARD_IMAGE_SERVERS},
    )


def granted_permissions() -> frozenset[str]:
    return frozenset(settings.CARD_GRANTED_PERMISSIONS) & frozenset(PERMISSIONS)


def host_sandbox() -> dict:
    """`hostCapabilities.sandbox`: what the host grants a view."""
    return {
        "permissions": {name: {} for name in PERMISSIONS if name in granted_permissions()},
        "csp": origin_policy().approved(),
    }


def canonical(host: str, csp: dict[str, list[str]]) -> str:
    """What is signed: the embedder and the declaration, one field a line in a fixed order."""
    return "\n".join([host, *(f"{name}={','.join(csp[name])}" for name in FIELDS if csp.get(name))])


def sign(csp: dict[str, list[str]]) -> str | None:
    """The host's word that it issued this policy for its own origin, which the sandbox checks before it
    serves a view under it. None when the host has no key, and then no card is shown. The key is read when
    needed, so a rotated secret reaches a running Worker."""
    key = runtime.get("SANDBOX_SIGNING_KEY")
    if not key:
        return None
    message = canonical(settings.PUBLIC_BASE_URL, csp).encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()
