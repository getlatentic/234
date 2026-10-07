# SPDX-License-Identifier: AGPL-3.0-or-later
"""The person's own view of what can act for them, in the chats drawer: the apps they connected through the
OAuth gateway (Claude, ChatGPT, …) and the personal agents they allowed to act as their account over PACT,
each with what it can use and a way to end it at once. Only a signed-in account has any of it: for anyone
else both addresses are 404."""

import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

from django.http import Http404, HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from chat.views.send import json_body
from oauth import grants as oauth_grants
from oauth.resources import name_of
from pact import brands
from pact import grants as pact_grants

APP, AGENT = "app", "agent"
SCOPE_WORDS = {
    "memory:read": "read your notes",
    "memory:write": "change your notes",
    "payments": "prepare payments",
}


def _owner(request: HttpRequest) -> str:
    account = getattr(request, "account", None)
    if account is None:
        raise Http404
    return account.owner


def _apps(owner: str) -> list[dict[str, str]]:
    return [
        {"kind": APP, "id": c.client_id, "name": c.name, "uses": ", ".join(name_of(n) for n in c.connectors)}
        for c in oauth_grants.clients_of(owner)
    ]


def _agents(owner: str) -> list[dict[str, str]]:
    found = []
    for grant in pact_grants.of_account(owner, int(time.time())):
        brand = brands.brands().get(grant.brand)
        words = ", ".join(SCOPE_WORDS.get(s, s) for s in grant.scopes.split())
        made = datetime.fromtimestamp(grant.created_at, UTC)
        since = f"{made.day} {made:%b %Y}"
        at = f"At {brand.name}: " if brand else ""
        name = urlsplit(grant.pa_issuer).netloc or grant.pa_issuer
        found.append({"kind": AGENT, "id": grant.id, "name": name, "uses": f"{at}{words}. Since {since}"})
    return found


def _listing(owner: str) -> JsonResponse:
    return JsonResponse({"connections": _apps(owner) + _agents(owner)}, headers={"Cache-Control": "no-store"})


@require_GET
def connections(request: HttpRequest) -> JsonResponse:
    return _listing(_owner(request))


@require_POST
def end(request: HttpRequest) -> JsonResponse:
    owner = _owner(request)
    body = json_body(request)
    kind, found = body.get("kind"), str(body.get("id", ""))
    if kind == APP:
        oauth_grants.end_client(owner, found)
    elif kind == AGENT:
        pact_grants.end(owner, found)
    else:
        return JsonResponse({"error": "Say which connection to end."}, status=400)
    return _listing(owner)
