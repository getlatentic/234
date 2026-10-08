# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the static home shell (shell.py) cannot hold because it belongs to the visitor: the CSRF token, who is
signed in, their chats, whether sign-in is offered, and whether the model is set up. One small answer, read by
the page when it loads; it makes the visitor and CSRF cookies the first time, like every page of the host."""

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_GET

from ..access import chats_of
from .pages import turn_settings

# A browser that names where a request comes from says "same-origin" for the page's own script.
OWN_SITE = {"same-origin", "none"}


def _sign_in() -> dict[str, str] | None:
    if not settings.SIGN_IN_ENABLED:
        return None
    emulator = settings.FIREBASE_AUTH_EMULATOR_HOST
    return {
        "apiKey": settings.FIREBASE_API_KEY,
        "authDomain": settings.FIREBASE_AUTH_DOMAIN,
        "projectId": settings.FIREBASE_PROJECT_ID,
        "emulator": f"http://{emulator}" if emulator else "",
    }


def _bot_check(account: object) -> str | None:
    """The Turnstile site key for a visitor who must pass it before a first message; a signed-in person has
    been identified by Google already and passes nothing."""
    return settings.TURNSTILE_SITE_KEY if settings.TURNSTILE_ENABLED and account is None else None


def _chats(request: HttpRequest) -> list[dict[str, object]]:
    return [
        {
            "id": chat.id,
            "title": chat.title,
            "url": reverse("chat:page", args=[chat.id]),
            "deleteUrl": reverse("chat:delete", args=[chat.id]),
            "mine": chat.owner == request.owner,
        }
        for chat in chats_of(request.owner)
    ]


@require_GET
def me(request: HttpRequest) -> HttpResponse:
    if request.headers.get("Sec-Fetch-Site", "same-origin") not in OWN_SITE:
        return HttpResponse(status=403)
    account = getattr(request, "account", None)
    response = JsonResponse(
        {
            "product": settings.PRODUCT_NAME,
            "csrf": get_token(request),
            "account": {"email": account.email, "initial": account.initial} if account else None,
            "signIn": _sign_in(),
            "botCheck": _bot_check(account),
            "memory": account is not None,
            "chats": _chats(request),
            "problem": turn_settings().model_problem(),
        }
    )
    patch_cache_control(response, no_store=True, private=True)
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    return response
