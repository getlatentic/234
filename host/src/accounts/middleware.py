# SPDX-License-Identifier: AGPL-3.0-or-later
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from . import session


class AccountMiddleware:
    """Puts `request.account` (the signed-in person, or None) on every request, before the visitor is looked
    at. A deployment without sign-in has no accounts, whatever cookie arrives."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.account = session.read(request) if settings.SIGN_IN_ENABLED else None
        return self.get_response(request)
