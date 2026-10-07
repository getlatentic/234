# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT Delegated's endpoints under /a2a/{brandId}/oauth/ (§5.1, §5.3): the RFC 8414 metadata, the keys that
sign delegation tokens and receipts, device authorization, the token endpoint, and the page where the person
signs in to 234 and decides. Every call an agent makes carries its personal-agent JWT, and its `client_id`
must be the JWT's issuer. All of them are 404 where the Brand does not offer delegation."""

import logging
import time
from collections.abc import Callable
from functools import wraps
from urllib.parse import urlsplit

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from chat.backend import get_backend

from . import addresses, delegation, device, grants, signing
from .brands import Brand, brands
from .errors import NO_STORE, OAuthRefused, RateLimited, oauth_error, rate_limited, unauthenticated
from .identity import Caller, Refused, caller_of

log = logging.getLogger(__name__)
MAX_FORM_BYTES = 8 * 1024
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
REFRESH_GRANT = "refresh_token"


def _brand(brand_id: str) -> Brand:
    found = brands().get(brand_id)
    if found is None or not delegation.offered(found):
        raise Http404
    return found


def from_agent(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """An agent's form POST: its JWT and its client_id checked, then the view, whose refusals are OAuth's."""

    @wraps(view)
    def wrapped(request: HttpRequest, brand_id: str) -> HttpResponse:
        brand = _brand(brand_id)
        try:
            caller = caller_of(request.headers.get("Authorization", ""), settings.PACT_AUDIENCE, time.time())
        except Refused as refused:
            log.info("pact oauth refused: %s", refused)
            return unauthenticated()
        if len(request.body) > MAX_FORM_BYTES or request.content_type != "application/x-www-form-urlencoded":
            return oauth_error(OAuthRefused("invalid_request", "Send a form of at most 8 KB."))
        if request.POST.get("client_id") != caller.issuer:
            return oauth_error(OAuthRefused("invalid_client", "client_id is the agent's issuer.", 401))
        try:
            return JsonResponse(view(request, brand, caller), headers=NO_STORE)
        except OAuthRefused as refused:
            return oauth_error(refused)
        except RateLimited:
            return rate_limited()

    return csrf_exempt(require_POST(wrapped))


@require_GET
def metadata(request: HttpRequest, brand_id: str) -> HttpResponse:
    brand = _brand(brand_id)
    return JsonResponse(
        {
            "issuer": addresses.issuer(brand),
            "device_authorization_endpoint": addresses.device_authorization_url(brand),
            "token_endpoint": addresses.token_url(brand),
            "jwks_uri": addresses.jwks_url(brand),
            "scopes_supported": list(brand.scopes),
            "grant_types_supported": [DEVICE_GRANT, REFRESH_GRANT],
        }
    )


@require_GET
def jwks(request: HttpRequest, brand_id: str) -> HttpResponse:
    _brand(brand_id)
    return JsonResponse(signing.jwks(), headers={"Cache-Control": "public, max-age=300"})


@from_agent
def device_authorization(request: HttpRequest, brand: Brand, caller: Caller) -> dict[str, object]:
    if not get_backend().rate_ok(f"pact-device:{caller.owner}"):
        raise RateLimited
    return device.start(brand, caller, request.POST.get("scope", ""), int(time.time()))


@from_agent
def token(request: HttpRequest, brand: Brand, caller: Caller) -> dict[str, object]:
    grant_type = request.POST.get("grant_type")
    if grant_type == DEVICE_GRANT:
        return device.take(brand, caller, request.POST.get("device_code", ""), int(time.time() * 1000))
    if grant_type == REFRESH_GRANT:
        return grants.refresh(brand, caller, request.POST.get("refresh_token", ""), int(time.time()))
    raise OAuthRefused("unsupported_grant_type", "Use the device code or the refresh token grant.")


def _decision(request: HttpRequest, brand: Brand) -> HttpResponse:
    account = request.account
    if account is None:
        return HttpResponse("Sign in first.", status=403, content_type="text/plain")
    if not get_backend().rate_ok(f"pact-consent:{account.owner}"):
        return HttpResponse("Too many requests. Try again in a minute.", 429, content_type="text/plain")
    allowed = tuple(request.POST.getlist("scope")) if request.POST.get("decision") == "allow" else ()
    code = request.POST.get("user_code", "")
    decided = device.decide(brand, code, device.Decision(account.owner, allowed), int(time.time()))
    outcome = "expired" if not decided else ("approved" if allowed else "denied")
    return render(request, "pact/device_done.html", {"brand": brand, "outcome": outcome})


@require_http_methods(["GET", "POST"])
def device_page(request: HttpRequest, brand_id: str) -> HttpResponse:
    brand = _brand(brand_id)
    if request.method == "POST":
        return _decision(request, brand)
    code = request.GET.get("user_code", "")
    found = device.waiting(brand, code, int(time.time())) if code else None
    asked = [(s, brand.scopes[s]) for s in found.scopes.split() if s in brand.scopes] if found else []
    page = {"brand": brand, "code": device.normal_code(code), "found": found, "asked": asked}
    return render(request, "pact/device.html", page | {"agent": _origin(found.pa_issuer) if found else ""})


def _origin(issuer: str) -> str:
    """The agent as the person can recognise it: its issuer's host."""
    return urlsplit(issuer).netloc or issuer
