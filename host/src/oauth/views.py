# SPDX-License-Identifier: AGPL-3.0-or-later
"""The authorization server's endpoints: discovery, authorize (the consent page), token, register, revoke.
All of them answer 404 while sign-in is off: a grant is made by a signed-in person."""

import json
import logging
from collections.abc import Callable
from functools import wraps

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from chat.backend import get_backend
from chat.security import page_policy

from . import grants, metadata
from .clients import InvalidClient
from .clients import register as register_client
from .cors import open_to_pages
from .fetch import fetch
from .requests import Refused, Unsafe, back_to_client, read
from .resources import connectors

log = logging.getLogger(__name__)
MAX_BODY = 16 * 1024
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def signing_in(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @wraps(view)
    def wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if not settings.SIGN_IN_ENABLED:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapped


def _client_address(request: HttpRequest) -> str:
    return request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("REMOTE_ADDR") or "unknown"


def _limited(request: HttpRequest) -> bool:
    return not get_backend().rate_ok(f"oauth:{_client_address(request)}")


def _error(error: str, status: int = 400, description: str | None = None) -> JsonResponse:
    body = {"error": error, **({"error_description": description} if description else {})}
    return JsonResponse(body, status=status, headers=NO_STORE)


@signing_in
@open_to_pages
@require_http_methods(["GET", "OPTIONS"])
def authorization_server(request: HttpRequest) -> HttpResponse:
    return JsonResponse(metadata.authorization_server())


@signing_in
@open_to_pages
@require_http_methods(["GET", "OPTIONS"])
def protected_resource(request: HttpRequest, connector: str) -> HttpResponse:
    if connector not in connectors():
        raise Http404
    return JsonResponse(metadata.protected_resource(connector))


def _consent(request: HttpRequest, params: dict[str, str]) -> HttpResponse:
    try:
        asked = read(params, fetch)
    except Unsafe as unsafe:
        log.info("authorization refused: %s", unsafe)
        return render(request, "oauth/refused.html", status=400)
    except Refused as refused:
        location = back_to_client(
            refused.redirect_uri, refused.state, error=refused.error, error_description=refused.description
        )
        return HttpResponseRedirect(location)
    if request.method == "GET" or request.account is None:
        page = render(request, "oauth/consent.html", {"asked": asked})
        # Allow answers with a redirect to the client, which the page's form-action must name.
        page["Content-Security-Policy"] = page_policy(form_targets=(asked.redirect_origin,))
        return page
    if request.POST.get("decision") != "allow":
        return HttpResponseRedirect(back_to_client(asked.redirect_uri, asked.state, error="access_denied"))
    approved = grants.Request(
        asked.client.client_id,
        request.account.owner,
        asked.redirect_uri,
        asked.challenge,
        asked.resource,
        asked.scope,
    )
    return HttpResponseRedirect(
        back_to_client(asked.redirect_uri, asked.state, code=grants.issue_code(approved))
    )


@signing_in
@require_http_methods(["GET", "POST"])
def authorize(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and _limited(request):
        return HttpResponse(
            "Too many requests. Try again in a minute.", status=429, content_type="text/plain"
        )
    source = request.GET if request.method == "GET" else request.POST
    return _consent(request, {k: source[k] for k in source if k != "csrfmiddlewaretoken"})


def _form(request: HttpRequest) -> dict[str, str] | None:
    if len(request.body) > MAX_BODY or request.content_type != "application/x-www-form-urlencoded":
        return None
    return {k: request.POST[k] for k in request.POST}


@signing_in
@csrf_exempt
@open_to_pages
@require_http_methods(["POST", "OPTIONS"])
def token(request: HttpRequest) -> HttpResponse:
    if _limited(request):
        return _error("slow_down", 429)
    form = _form(request)
    if form is None:
        return _error("invalid_request", description="Send the form as application/x-www-form-urlencoded.")
    try:
        if form.get("grant_type") == "authorization_code":
            issued = grants.redeem_code(
                form.get("code", ""),
                form.get("client_id", ""),
                form.get("redirect_uri", ""),
                form.get("code_verifier", ""),
                form.get("resource"),
            )
        elif form.get("grant_type") == "refresh_token":
            issued = grants.refresh(
                form.get("refresh_token", ""), form.get("client_id", ""), form.get("resource")
            )
        else:
            return _error("unsupported_grant_type")
    except grants.InvalidGrant as refused:
        log.info("token refused: %s", refused)
        return _error("invalid_grant")
    return JsonResponse(issued, headers=NO_STORE)


@signing_in
@csrf_exempt
@open_to_pages
@require_http_methods(["POST", "OPTIONS"])
def register(request: HttpRequest) -> HttpResponse:
    if _limited(request):
        return _error("slow_down", 429)
    if len(request.body) > MAX_BODY:
        return _error("invalid_client_metadata", description="The body is too large.")
    try:
        registered = register_client(json.loads(request.body or b"null"))
    except ValueError:
        return _error("invalid_client_metadata", description="The body must be JSON.")
    except InvalidClient as refused:
        return _error(refused.error, description=str(refused))
    return JsonResponse(registered, status=201, headers=NO_STORE)


@signing_in
@csrf_exempt
@open_to_pages
@require_http_methods(["POST", "OPTIONS"])
def revoke(request: HttpRequest) -> HttpResponse:
    form = _form(request)
    if form is None or not form.get("token"):
        return _error("invalid_request")
    grants.revoke(form["token"])
    return HttpResponse(status=200)
