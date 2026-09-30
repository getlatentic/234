# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turns an ID token from the page into an identity, with the deployment's settings and Google's keys."""

import time

from django.conf import settings

from .firebase_token import Identity, verify_id_token
from .keys import GoogleKeys
from .transport import fetch

_keys: GoogleKeys | None = None


def google_keys() -> GoogleKeys:
    """One key cache per isolate, so the keys are fetched once an hour and not once a sign-in."""
    global _keys
    if _keys is None:
        _keys = GoogleKeys(fetch, url=settings.FIREBASE_KEYS_URL)
    return _keys


def set_keys(keys: GoogleKeys | None) -> None:
    global _keys
    _keys = keys


def identity_of(token: object, now: float | None = None) -> Identity:
    return verify_id_token(
        token,
        project=settings.FIREBASE_PROJECT_ID,
        keys=google_keys(),
        now=time.time() if now is None else now,
        emulator=bool(settings.FIREBASE_AUTH_EMULATOR_HOST),
    )
