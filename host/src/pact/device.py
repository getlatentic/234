# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT §5.3 on RFC 8628: a personal agent asks for scopes and gets a code the person enters, or a link that
carries it; the person signs in to 234 and decides on the consent page; the agent polls the token endpoint
until the decision, and takes the grant once. A device code is bound to the User of the agent that asked:
another User of the same agent, or another agent, polls it in vain."""

import secrets
from dataclasses import dataclass

from config.sql import returning

from . import addresses, grants
from .brands import Brand
from .errors import OAuthRefused
from .identity import Caller
from .models import DeviceAuthorization

DEVICE_SECONDS = 600
INTERVAL_SECONDS = 5
# RFC 8628 §3.5 asks the client to wait `interval` between polls; a second of slack covers the network.
SLOW_DOWN_MS = (INTERVAL_SECONDS - 1) * 1000
USER_CODE_LETTERS = "BCDFGHJKLMNPQRSTVWXZ"  # RFC 8628 §6.1: no vowels, so no word is spelled
MAX_SCOPE_CHARS = 200


def _user_code() -> str:
    letters = "".join(secrets.choice(USER_CODE_LETTERS) for _ in range(8))
    return f"{letters[:4]}-{letters[4:]}"


def normal_code(entered: str) -> str:
    """A code as typed (any case, with or without the hyphen or spaces) in its stored form."""
    letters = "".join(c for c in entered.upper() if c.isalpha())[:8]
    return f"{letters[:4]}-{letters[4:]}" if len(letters) == 8 else ""


def _asked(brand: Brand, scope: str) -> str:
    asked = list(dict.fromkeys(scope.split()))
    if not asked or len(scope) > MAX_SCOPE_CHARS or not set(asked) <= set(brand.scopes):
        raise OAuthRefused("invalid_scope", "Ask for scopes this Brand's card lists.")
    return " ".join(asked)


def start(brand: Brand, caller: Caller, scope: str, now: int) -> dict[str, object]:
    asked = _asked(brand, scope)
    device_code = f"dc_{secrets.token_urlsafe(32)}"
    for _ in range(3):
        user_code = _user_code()
        made = returning(
            "INSERT INTO pact_deviceauthorization (digest, user_code, brand, pa_issuer, pa_owner, scopes, "
            "status, granted, account, expires_at, polled_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, '', '', %s, 0) "
            "ON CONFLICT (user_code) DO NOTHING RETURNING digest",
            [grants.digest(device_code), user_code, brand.id, caller.issuer, caller.owner, asked,
             DeviceAuthorization.PENDING, now + DEVICE_SECONDS],
        )  # fmt: skip
        if made:
            page = addresses.verification_url(brand)
            return {
                "device_code": device_code,
                "user_code": user_code,
                "verification_uri": page,
                "verification_uri_complete": f"{page}?user_code={user_code}",
                "expires_in": DEVICE_SECONDS,
                "interval": INTERVAL_SECONDS,
            }
    raise OAuthRefused("server_error", "No user code could be made.", 500)


def waiting(brand: Brand, entered: str, now: int) -> DeviceAuthorization | None:
    """The request a code names, while the person can still decide on it."""
    code = normal_code(entered)
    return DeviceAuthorization.objects.filter(
        user_code=code, brand=brand.id, status=DeviceAuthorization.PENDING, expires_at__gt=now
    ).first()


@dataclass(frozen=True)
class Decision:
    account: str
    allowed: tuple[str, ...]
    """Empty: denied."""


def decide(brand: Brand, entered: str, decision: Decision, now: int) -> bool:
    """Records the person's decision once; False when the code is no longer waiting for one."""
    found = waiting(brand, entered, now)
    if found is None:
        return False
    allowed = [s for s in found.scopes.split() if s in decision.allowed]
    status = DeviceAuthorization.APPROVED if allowed else DeviceAuthorization.DENIED
    return bool(
        returning(
            "UPDATE pact_deviceauthorization SET status = %s, granted = %s, account = %s "
            "WHERE digest = %s AND status = %s AND expires_at > %s RETURNING digest",
            [status, " ".join(allowed), decision.account, found.digest, DeviceAuthorization.PENDING, now],
        )
    )


def _pending(found: DeviceAuthorization, now_ms: int) -> OAuthRefused:
    too_soon = now_ms - found.polled_at < SLOW_DOWN_MS
    DeviceAuthorization.objects.filter(digest=found.digest).update(polled_at=now_ms)
    if too_soon:
        return OAuthRefused("slow_down", f"Poll at most every {INTERVAL_SECONDS} seconds.")
    return OAuthRefused("authorization_pending", "The person has not decided yet.")


def take(brand: Brand, caller: Caller, device_code: str, now_ms: int) -> dict[str, object]:
    """The token response once the person approved; otherwise the RFC 8628 error for where it stands."""
    now = now_ms // 1000
    found = DeviceAuthorization.objects.filter(digest=grants.digest(device_code), brand=brand.id).first()
    if found is None or found.pa_owner != caller.owner:
        raise OAuthRefused("invalid_grant", "Unknown device code.")
    if found.status == DeviceAuthorization.DENIED:
        raise OAuthRefused("access_denied", "The person said no.")
    if found.expires_at <= now and found.status != DeviceAuthorization.TAKEN:
        raise OAuthRefused("expired_token", "The code expired before it was used.")
    if found.status == DeviceAuthorization.PENDING:
        raise _pending(found, now_ms)
    claimed = returning(
        "UPDATE pact_deviceauthorization SET status = %s WHERE digest = %s AND status = %s RETURNING digest",
        [DeviceAuthorization.TAKEN, found.digest, DeviceAuthorization.APPROVED],
    )
    if not claimed:
        raise OAuthRefused("invalid_grant", "That device code has been used.")
    grant = grants.make(brand, found.pa_issuer, found.pa_owner, found.account, found.granted, now)
    return grants.tokens(grant, brand, now)
