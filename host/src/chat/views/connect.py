# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where Paystack Index sends the person's browser after they sign in there (GET /connect/index/callback).

The page is the redirect address 234 registered at Index. It acts only for the signed-in account whose
browser arrives, and hands the code and the `state` to the merchants connector as that account: the
connector takes the state once, only for an attempt that account started and that is still open, so a link
opened by anyone else, twice, or late connects nothing. The code is exchanged there; no token passes through
this page, the browser or the chat. A sign-in Index reports as refused (`error=access_denied`) ends the
attempt the same way."""

import re

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from ..backend import get_backend

MAX_PARAMETER = 2000
REFUSAL_CODE = re.compile(r"^[A-Z][A-Z_]+:\s*")
NOT_SIGNED_IN = "Sign in to 234 in this browser, then connect again from the card in your chat."


def _outcome(request: HttpRequest, state: str, code: str, error: str) -> tuple[str, str]:
    """`connected`, `declined` or `refused`, and the connector's words for a refusal."""
    name, arguments = (
        ("connection_declined", {"state": state})
        if error
        else ("complete_connection", {"code": code, "state": state})
    )
    answer = get_backend().connect_account(request.account.owner, name, arguments)
    if answer.get("isError"):
        said = next((b.get("text", "") for b in answer.get("content", []) if b.get("type") == "text"), "")
        return "refused", REFUSAL_CODE.sub("", said)
    return ("declined" if error else "connected"), ""


@require_GET
def index_callback(request: HttpRequest) -> HttpResponse:
    if request.account is None:
        return render(
            request, "chat/connect_done.html", {"outcome": "refused", "said": NOT_SIGNED_IN}, status=401
        )
    if not get_backend().rate_ok(f"connect-index:{request.account.owner}"):
        return HttpResponse("Too many tries. Wait a minute.", status=429, content_type="text/plain")
    state, code, error = (request.GET.get(name, "") for name in ("state", "code", "error"))
    if not state or len(state) > MAX_PARAMETER or len(code) > MAX_PARAMETER or not (code or error):
        return render(request, "chat/connect_done.html", {"outcome": "refused", "said": ""}, status=400)
    outcome, said = _outcome(request, state, code, error)
    status = 200 if outcome != "refused" else 400
    response = render(request, "chat/connect_done.html", {"outcome": outcome, "said": said}, status=status)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response
