# SPDX-License-Identifier: AGPL-3.0-or-later
"""The signed-in session: our own cookie, made once the Firebase ID token is verified, never holding it.

The cookie is HttpOnly, Secure (outside development), SameSite=Lax and host-only (no Domain), lasts 30
days, and is a new value at every sign-in (a random nonce is inside it), so a value set before sign-in is
never the one kept after it. It holds the owner key, the email (to show it) and the nonce, signed with
Django's signer, salted for this use; it is not encrypted, and its holder is the one person who may read
it. It cannot be revoked one cookie at a time: signing out deletes it in this browser, and a new
DJANGO_SECRET_KEY ends every session.
"""

import secrets
from dataclasses import dataclass

from django.conf import settings
from django.core import signing
from django.http import HttpRequest, HttpResponse

COOKIE = "session"
SALT = "accounts.session"
LIFETIME = 30 * 24 * 3600


@dataclass(frozen=True)
class Account:
    owner: str
    email: str

    @property
    def initial(self) -> str:
        return self.email[:1].upper()


def read(request: HttpRequest) -> Account | None:
    raw = request.COOKIES.get(COOKIE)
    if not raw:
        return None
    try:
        data = signing.loads(raw, salt=SALT, max_age=LIFETIME)
        owner, email = data["o"], data["e"]
    except signing.BadSignature, KeyError, TypeError:
        return None
    return Account(owner, email) if isinstance(owner, str) and isinstance(email, str) else None


def start(response: HttpResponse, account: Account) -> None:
    value = signing.dumps(
        {"o": account.owner, "e": account.email, "n": secrets.token_hex(8)}, salt=SALT, compress=False
    )
    response.set_cookie(
        COOKIE, value, max_age=LIFETIME, httponly=True, samesite="Lax", secure=not settings.DEBUG, path="/"
    )


def end(response: HttpResponse) -> None:
    response.delete_cookie(COOKIE, path="/", samesite="Lax")
