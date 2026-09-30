# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /auth/session (an ID token in, our session cookie out) and POST /auth/signout.

Both are POSTs behind Django's CSRF check like every other POST of the page. A sign-in is rate limited per
client address. The caller is told only that the token was or was not accepted: the reason is in the log.
"""

import logging

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from chat import visitor
from chat.backend import get_backend
from chat.views.send import json_body

from . import session
from .adopt import adopt
from .firebase_token import InvalidToken
from .keys import KeysUnavailable
from .owner import account_owner
from .service import identity_of

log = logging.getLogger(__name__)


def _client(request: HttpRequest) -> str:
    return request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("REMOTE_ADDR") or request.owner


@require_POST
def sign_in(request: HttpRequest) -> HttpResponse:
    if not settings.SIGN_IN_ENABLED:
        raise Http404
    if not get_backend().rate_ok(f"auth:{_client(request)}"):
        return JsonResponse({"error": "rate_limited"}, status=429)
    try:
        identity = identity_of(json_body(request).get("idToken"))
    except InvalidToken as refused:
        log.info("sign-in refused: %s", refused)
        return JsonResponse({"error": "invalid"}, status=401)
    except KeysUnavailable as unavailable:
        log.warning("sign-in unavailable: %s", unavailable)
        return JsonResponse({"error": "unavailable"}, status=503)
    owner = account_owner(identity.uid, settings.ACCOUNT_KEY)
    anonymous = visitor.visitor_of(request)
    if anonymous is not None and request.account is None:
        adopt(f"{visitor.OWNER_PREFIX}{anonymous}", owner)
    response = JsonResponse({"email": identity.email})
    session.start(response, session.Account(owner, identity.email))
    visitor.forget(response)
    return response


@require_POST
def sign_out(request: HttpRequest) -> HttpResponse:
    if not settings.SIGN_IN_ENABLED:
        raise Http404
    response = HttpResponse(status=204)
    if request.account is not None:
        session.end(response)
        visitor.issue(response)
    return response
