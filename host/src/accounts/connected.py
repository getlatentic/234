# SPDX-License-Identifier: AGPL-3.0-or-later
"""The person's own view of what can act for them, in the chats drawer: the apps they connected through the
OAuth gateway (Claude, ChatGPT, …), the personal agents they allowed to act as their account over PACT, and
the Brands where they let 234 act for them (turns/reach/), each with what it can use and a way to end it at
once. Only a signed-in account has any of it: for anyone else both addresses are 404."""

import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

from django.http import Http404, HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from chat.backend import get_backend
from chat.views.send import json_body
from oauth import grants as oauth_grants
from oauth.resources import name_of
from pact import brands
from pact import grants as pact_grants
from reach.models import Conversation, Delegation
from turns.ledger_owner import ledger_owner

APP, AGENT, BRAND = "app", "agent", "brand"
SCOPE_WORDS = {
    "memory:read": "read your notes",
    "memory:write": "change your notes",
    "payments": "prepare payments",
}

NOT_REVOKED = "{brand} doesn't let 234 end it there. You can in your {brand} settings."


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
        since = _day(grant.created_at)
        at = f"At {brand.name}: " if brand else ""
        name = urlsplit(grant.pa_issuer).netloc or grant.pa_issuer
        found.append({"kind": AGENT, "id": grant.id, "name": name, "uses": f"{at}{words}. Since {since}"})
    return found


def _brands(owner: str) -> list[dict[str, str]]:
    held = Delegation.objects.filter(owner=ledger_owner(owner)).order_by("brand_name")
    return [
        {
            "kind": BRAND,
            "id": d.brand,
            "name": d.brand_name,
            "uses": f"234 acts for you there. Since {_day(d.updated_at)}",
        }
        for d in held
    ]


def _day(at: int) -> str:
    made = datetime.fromtimestamp(at, UTC)
    return f"{made.day} {made:%b %Y}"


def _end_brand(owner: str, brand: str) -> str:
    """Ends it at the Brand too where the Brand lets 234 revoke (turns/reach/signing_in.py); where it does
    not, the person is told to end it there. 234 forgets its tokens either way, and without 234's own key they
    are no use to anyone."""
    key = ledger_owner(owner)
    held = Delegation.objects.filter(owner=key, brand=brand).first()
    revoked = held is not None and get_backend().end_brand(owner, brand)
    Delegation.objects.filter(owner=key, brand=brand).delete()
    Conversation.objects.filter(owner=key, brand=brand).delete()
    if held is None or revoked:
        return ""
    return NOT_REVOKED.format(brand=held.brand_name)


def _listing(owner: str, note: str = "") -> JsonResponse:
    found = _apps(owner) + _agents(owner) + _brands(owner)
    body: dict[str, object] = {"connections": found}
    if note:
        body["note"] = note
    return JsonResponse(body, headers={"Cache-Control": "no-store"})


@require_GET
def connections(request: HttpRequest) -> JsonResponse:
    return _listing(_owner(request))


@require_POST
def end(request: HttpRequest) -> JsonResponse:
    owner = _owner(request)
    body = json_body(request)
    kind, found = body.get("kind"), str(body.get("id", ""))
    note = ""
    if kind == APP:
        oauth_grants.end_client(owner, found)
    elif kind == AGENT:
        pact_grants.end(owner, found)
    elif kind == BRAND:
        note = _end_brand(owner, found)
    else:
        return JsonResponse({"error": "Say which connection to end."}, status=400)
    return _listing(owner, note)
