# SPDX-License-Identifier: AGPL-3.0-or-later
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

DIRECTIVES = {
    "default-src": ["'self'"],
    "script-src": ["'self'"],
    "style-src": ["'self'"],
    "img-src": ["'self'", "data:"],
    "connect-src": ["'self'"],
    "frame-src": [],
    "base-uri": ["'none'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
}

# What the Firebase sign-in popup needs beyond the page's own origin, and only where sign-in is on
# (docs/auth.md): its loader script (which also beacons to its own host and, now and then, to one pixel of
# www.google.com: named by its path, not the host), the auth domain's handler frame, and the two API hosts the
# SDK calls.
SIGN_IN_SOURCES = {
    "script-src": ["https://apis.google.com"],
    "connect-src": [
        "https://identitytoolkit.googleapis.com",
        "https://securetoken.googleapis.com",
        "https://apis.google.com",
        "https://www.google.com/images/cleardot.gif",
    ],
}


def sign_in_sources() -> dict[str, list[str]]:
    if not settings.SIGN_IN_ENABLED:
        return {}
    sources = {name: list(values) for name, values in SIGN_IN_SOURCES.items()}
    sources["frame-src"] = [f"https://{settings.FIREBASE_AUTH_DOMAIN}"]
    if settings.FIREBASE_AUTH_EMULATOR_HOST:
        origin = f"http://{settings.FIREBASE_AUTH_EMULATOR_HOST}"
        sources["connect-src"].append(origin)
        sources["frame-src"].append(origin)
    return sources


def page_policy() -> str:
    """The only frames a page may hold are the card sandbox's, from its own origin, and, where sign-in is on,
    the Firebase handler's."""
    extra = sign_in_sources()
    parts = []
    for name, base in DIRECTIVES.items():
        sources = base + (
            [settings.SANDBOX_ORIGIN] if name == "frame-src" and settings.SANDBOX_ORIGIN else []
        )
        sources += extra.get(name, [])
        parts.append(f"{name} {' '.join(sources or ["'none'"])}")
    return "; ".join(parts)


class ContentSecurityPolicyMiddleware:
    """Pages run only their own scripts and frame only the card sandbox."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", page_policy())
        return response
