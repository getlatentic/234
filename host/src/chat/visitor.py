# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who is asking: a signed-in person (`request.account`, accounts/) is their account's owner; anyone else is a
visitor, and a signed cookie holds a random visitor id. Chats belong to that owner.

The cookie is an HMAC over the id (Django's signing, salted for this use), so it cannot be forged or
edited, and it is HttpOnly so no script reads it. A missing or invalid cookie gets a fresh visitor.
"""

import secrets
from collections.abc import Callable

from django.conf import settings
from django.core.signing import BadSignature
from django.http import HttpRequest, HttpResponse

COOKIE = "visitor"
SALT = "chat.visitor"
YEAR = 365 * 24 * 3600
OWNER_PREFIX = "v:"


def visitor_of(request: HttpRequest) -> str | None:
    try:
        value = request.get_signed_cookie(COOKIE, salt=SALT)
    except BadSignature, KeyError:
        return None
    return value if len(value) == 32 and value.isalnum() else None


def _set(response: HttpResponse, visitor: str) -> None:
    response.set_signed_cookie(
        COOKIE, visitor, salt=SALT, max_age=YEAR, httponly=True, samesite="Lax", secure=not settings.DEBUG
    )


def issue(response: HttpResponse) -> None:
    """A fresh visitor: sign-out ends as an anonymous stranger to everything the account held."""
    _set(response, secrets.token_hex(16))


def forget(response: HttpResponse) -> None:
    response.delete_cookie(COOKIE, samesite="Lax")


class VisitorMiddleware:
    """Puts `request.owner` on every request and sets the cookie the first time. A signed-in person is their
    account's owner and needs no visitor cookie."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        account = getattr(request, "account", None)
        known = visitor_of(request)
        visitor = known or secrets.token_hex(16)
        request.owner = account.owner if account else f"{OWNER_PREFIX}{visitor}"
        response = self.get_response(request)
        if known is None and account is None and getattr(request, "wants_visitor_cookie", True):
            _set(response, visitor)
        return response
