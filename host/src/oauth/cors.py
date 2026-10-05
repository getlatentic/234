# SPDX-License-Identifier: AGPL-3.0-or-later
"""CORS for the endpoints an MCP client may call from a page: discovery, token, registration, revocation and
the MCP gateway. None of them reads a cookie, so any origin may call them."""

from collections.abc import Callable
from functools import wraps

from django.http import HttpRequest, HttpResponse

ALLOWED_HEADERS = "authorization, content-type, mcp-protocol-version, mcp-session-id, last-event-id"
EXPOSED_HEADERS = "mcp-session-id, www-authenticate"


def open_to_pages(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @wraps(view)
    def wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        response = HttpResponse(status=204) if request.method == "OPTIONS" else view(request, *args, **kwargs)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Headers"] = ALLOWED_HEADERS
        response["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response["Access-Control-Expose-Headers"] = EXPOSED_HEADERS
        response["Access-Control-Max-Age"] = "600"
        return response

    return wrapped
