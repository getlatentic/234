# SPDX-License-Identifier: AGPL-3.0-or-later
"""PACT §6: A2A errors in the AIP-193 envelope, the answers that carry no A2A body (401, 404, 405, 429), and
the OAuth errors of the Delegated endpoints (RFC 6749 §5.2, RFC 8628 §3.5)."""

from django.http import HttpResponse, JsonResponse

A2A_JSON = "application/a2a+json"
REASONS = {
    "INVALID_PARAMS": (400, "INVALID_ARGUMENT"),
    "CONTENT_TYPE_NOT_SUPPORTED": (400, "INVALID_ARGUMENT"),
    "UNSUPPORTED_OPERATION": (400, "FAILED_PRECONDITION"),
    "PUSH_NOTIFICATION_NOT_SUPPORTED": (400, "FAILED_PRECONDITION"),
    "TASK_NOT_FOUND": (404, "NOT_FOUND"),
    "INTERNAL": (500, "INTERNAL"),
}


class A2AError(Exception):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def a2a_json(body: dict, status: int = 200) -> JsonResponse:
    return JsonResponse(body, status=status, content_type=A2A_JSON, json_dumps_params={"ensure_ascii": False})


def error_response(error: A2AError) -> JsonResponse:
    http, status = REASONS[error.reason]
    detail = {
        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
        "reason": error.reason,
        "domain": "a2a-protocol.org",
    }
    return a2a_json(
        {"error": {"code": http, "status": status, "message": str(error), "details": [detail]}}, http
    )


def unauthenticated(error: str | None = None) -> HttpResponse:
    response = HttpResponse(status=401)
    response["WWW-Authenticate"] = 'Bearer realm="a2a"' + (f', error="{error}"' if error else "")
    return response


def no_route(allowed: tuple[str, ...] = ()) -> HttpResponse:
    if not allowed:
        return HttpResponse(status=404)
    return HttpResponse(status=405, headers={"Allow": ", ".join(allowed)})


def rate_limited() -> HttpResponse:
    return HttpResponse(status=429, headers={"Retry-After": "60"})


class RateLimited(Exception):
    """Answered with 429 and Retry-After (§6)."""


class OAuthRefused(Exception):
    def __init__(self, error: str, description: str = "", status: int = 400) -> None:
        super().__init__(description or error)
        self.error, self.description, self.status = error, description, status


NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def oauth_error(refused: OAuthRefused) -> JsonResponse:
    body = {"error": refused.error}
    if refused.description:
        body["error_description"] = refused.description
    return JsonResponse(body, status=refused.status, headers=NO_STORE)
