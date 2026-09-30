# SPDX-License-Identifier: AGPL-3.0-or-later
from django.conf import settings
from django.http import HttpRequest


def account(request: HttpRequest) -> dict[str, object]:
    """What the drawer needs to offer sign-in: whether it exists, who is signed in, and the Firebase web app's
    public identifiers. Nothing here is a secret."""
    if not settings.SIGN_IN_ENABLED:
        return {"sign_in_enabled": False}
    emulator = settings.FIREBASE_AUTH_EMULATOR_HOST
    return {
        "sign_in_enabled": True,
        "account": getattr(request, "account", None),
        "firebase": {
            "apiKey": settings.FIREBASE_API_KEY,
            "authDomain": settings.FIREBASE_AUTH_DOMAIN,
            "projectId": settings.FIREBASE_PROJECT_ID,
            "emulator": f"http://{emulator}" if emulator else "",
        },
    }
