# SPDX-License-Identifier: AGPL-3.0-or-later
"""A2A errors as the HTTP+JSON binding reports them: an HTTP status, a google.rpc status, and an ErrorInfo
whose reason the official clients map back to their own error types."""

from typing import Any

DOMAIN = "a2a-protocol.org"
ERROR_INFO = "type.googleapis.com/google.rpc.ErrorInfo"


class A2AError(Exception):
    http = 500
    status = "INTERNAL"
    reason = "INTERNAL_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def payload(self) -> dict[str, Any]:
        info = {"@type": ERROR_INFO, "reason": self.reason, "domain": DOMAIN, "metadata": {}}
        return {
            "error": {"code": self.http, "status": self.status, "message": self.message, "details": [info]}
        }


class TaskNotFound(A2AError):
    http, status, reason = 404, "NOT_FOUND", "TASK_NOT_FOUND"


class InvalidParams(A2AError):
    http, status, reason = 400, "INVALID_ARGUMENT", "INVALID_PARAMS"


class InvalidRequest(A2AError):
    http, status, reason = 400, "INVALID_ARGUMENT", "INVALID_REQUEST"


class VersionNotSupported(A2AError):
    http, status, reason = 400, "FAILED_PRECONDITION", "VERSION_NOT_SUPPORTED"


class UnsupportedOperation(A2AError):
    http, status, reason = 400, "FAILED_PRECONDITION", "UNSUPPORTED_OPERATION"


class TaskNotCancelable(A2AError):
    http, status, reason = 400, "FAILED_PRECONDITION", "TASK_NOT_CANCELABLE"


class Unauthenticated(A2AError):
    http, status, reason = 401, "UNAUTHENTICATED", "UNAUTHENTICATED"


class RateLimited(A2AError):
    http, status, reason = 429, "RESOURCE_EXHAUSTED", "RATE_LIMITED"
