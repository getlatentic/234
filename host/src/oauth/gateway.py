# SPDX-License-Identifier: AGPL-3.0-or-later
"""/mcp/<connector>: each connector as a protected MCP server for any MCP client with a 234 access token.

The token is checked here (issued by this server, for this connector, not expired) and goes no further: the
connector is called over the host's own binding with the host's token, for the ledger owner of the account
that approved the grant. Only the MCP headers are passed on, so a caller cannot name an owner itself."""

from django.http import Http404, HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from chat.backend import get_backend
from turns.hub import MEMORY_SERVER
from turns.ledger_owner import ledger_owner

from .cors import open_to_pages
from .grants import access_of
from .resources import connectors, metadata_url, resource_url, scope_of
from .views import signing_in

MAX_BODY = 1024 * 1024
PASSED_ON = ("mcp-protocol-version", "mcp-session-id", "last-event-id")


def challenge(connector: str, error: str | None = None) -> HttpResponse:
    params = [f'resource_metadata="{metadata_url(connector)}"', f'scope="{scope_of(connector)}"']
    if error:
        params.insert(0, f'error="{error}"')
    response = HttpResponse(status=401)
    response["WWW-Authenticate"] = "Bearer " + ", ".join(params)
    return response


def _bearer(request: HttpRequest) -> str | None:
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


@signing_in
@csrf_exempt
@open_to_pages
def mcp(request: HttpRequest, connector: str) -> HttpResponse:
    if connector not in connectors():
        raise Http404
    token = _bearer(request)
    if token is None:
        return challenge(connector)
    access = access_of(token)
    if access is None or access.resource != resource_url(connector):
        return challenge(connector, "invalid_token")
    if request.method != "POST":
        return HttpResponse(status=405, headers={"Allow": "POST"})
    if len(request.body) > MAX_BODY:
        return HttpResponse(status=413)
    headers = {name: request.headers[name] for name in PASSED_ON if name in request.headers}
    status, answered, body = get_backend().relay(
        connector, request.body, headers, ledger_owner(access.owner), notes=connector == MEMORY_SERVER
    )
    response = HttpResponse(
        body, status=status, content_type=answered.get("content-type", "application/json")
    )
    if "mcp-session-id" in answered:
        response["mcp-session-id"] = answered["mcp-session-id"]
    return response
