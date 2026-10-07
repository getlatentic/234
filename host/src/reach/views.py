# SPDX-License-Identifier: AGPL-3.0-or-later
"""234's public key as a personal agent (PACT §3.1): the JWKS at its issuer, where a Brand's Provider reads
the keys that sign 234's personal-agent JWTs. 404 where 234 reaches no Brand."""

from functools import cache

from django.conf import settings
from django.http import Http404, HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from signatures.private_key import from_jwk


@cache
def _public() -> dict[str, list[dict[str, str]]]:
    return {"keys": [from_jwk(settings.PACT_AGENT_KEY).public()]}


@require_GET
def jwks(request: HttpRequest) -> JsonResponse:
    request.wants_visitor_cookie = False
    if not (settings.PACT_AGENT_KEY and settings.PACT_REACH):
        raise Http404
    return JsonResponse(_public(), headers={"Cache-Control": "public, max-age=300"})
