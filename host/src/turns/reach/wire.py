# SPDX-License-Identifier: AGPL-3.0-or-later
"""What 234 sends a Brand and reads back (PACT §4, §5.3, §5.5, §6): a message with the personal-agent JWT and,
when the person gave one, their delegation token; the agent's reply, with its receipt; or a step-up naming
the scopes the Brand needs. The OAuth calls are form posts with the same JWT."""

import uuid
from dataclasses import dataclass
from typing import Any

import httpx

MAX_ANSWER_BYTES = 256 * 1024
DELEGATION_HEADER = "X-A2A-User-Delegation"


class BrandUnavailable(Exception):
    """The Brand did not answer, or answered something PACT does not allow."""


class TokenRejected(Exception):
    """The Brand refused the delegation token (401, error="invalid_token")."""


class BrandError(Exception):
    """An A2A error envelope (§6): its reason and message."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason, self.message = reason, message


@dataclass(frozen=True)
class Reply:
    text: str
    context_id: str | None
    receipt: dict[str, Any] | None = None
    missing_scopes: tuple[str, ...] = ()


def _text_of(message: dict[str, Any]) -> str:
    return "\n".join(
        str(p["text"]) for p in message.get("parts") or [] if isinstance(p, dict) and "text" in p
    )


def _read(answer: httpx.Response) -> dict[str, Any]:
    if len(answer.content) > MAX_ANSWER_BYTES:
        raise BrandUnavailable("The Brand's answer is too large.")
    try:
        body = answer.json()
    except ValueError as error:
        raise BrandUnavailable(f"The Brand answered {answer.status_code} without JSON.") from error
    if not isinstance(body, dict):
        raise BrandUnavailable("The Brand's answer is not a JSON object.")
    return body


def _failed(answer: httpx.Response, delegated: bool) -> Exception:
    if answer.status_code == 401:
        challenge = answer.headers.get("www-authenticate", "")
        if delegated and 'error="invalid_token"' in challenge:
            return TokenRejected()
        return BrandUnavailable("The Brand refused 234's identity (401).")
    if answer.status_code == 429:
        return BrandUnavailable("The Brand asks to wait before the next message (429).")
    try:
        error = _read(answer).get("error") or {}
        reason = (error.get("details") or [{}])[0].get("reason", "")
        return BrandError(str(reason), str(error.get("message", "")))
    except BrandUnavailable, AttributeError, IndexError, TypeError:
        return BrandUnavailable(f"The Brand answered {answer.status_code}.")


def _reply(body: dict[str, Any]) -> Reply:
    if isinstance(body.get("task"), dict):
        task = body["task"]
        missing = (task.get("metadata") or {}).get("pact.missingScopes") or []
        if (task.get("status") or {}).get("state") != "TASK_STATE_AUTH_REQUIRED" or not missing:
            raise BrandUnavailable("The Brand answered with a task 234 cannot follow.")
        said = _text_of((task.get("status") or {}).get("message") or {})
        return Reply(said, task.get("contextId"), None, tuple(str(s) for s in missing))
    message = body.get("message")
    if not isinstance(message, dict) or message.get("role") != "ROLE_AGENT":
        raise BrandUnavailable("The Brand's reply is not an agent's message.")
    receipt = (message.get("metadata") or {}).get("pact.receipt")
    return Reply(_text_of(message), message.get("contextId"), receipt if isinstance(receipt, dict) else None)


async def send(
    client: httpx.AsyncClient,
    interface_url: str,
    pa_jwt: str,
    text: str,
    context_id: str | None,
    delegation_token: str | None,
) -> Reply:
    message: dict[str, Any] = {
        "messageId": str(uuid.uuid4()),
        "role": "ROLE_USER",
        "parts": [{"text": text, "mediaType": "text/plain"}],
    }
    if context_id:
        message["contextId"] = context_id
    headers = {"authorization": f"Bearer {pa_jwt}", "a2a-version": "1.0", "content-type": "application/json"}
    if delegation_token:
        headers[DELEGATION_HEADER] = f"Bearer {delegation_token}"
    try:
        answer = await client.post(
            f"{interface_url}/message:send", json={"message": message}, headers=headers
        )
    except httpx.HTTPError as error:
        raise BrandUnavailable("The Brand could not be reached.") from error
    if answer.status_code != 200:
        raise _failed(answer, bool(delegation_token))
    return _reply(_read(answer))


async def form(
    client: httpx.AsyncClient, url: str, pa_jwt: str, fields: dict[str, str]
) -> tuple[int, dict[str, Any]]:
    """An OAuth form post; its status and JSON body (an OAuth error's body included)."""
    headers = {"authorization": f"Bearer {pa_jwt}", "accept": "application/json"}
    try:
        answer = await client.post(url, data=fields, headers=headers)
    except httpx.HTTPError as error:
        raise BrandUnavailable("The Brand's sign-in service could not be reached.") from error
    if answer.status_code == 401 and "error" not in answer.text:
        raise BrandUnavailable("The Brand refused 234's identity (401).")
    return answer.status_code, _read(answer)


async def json_of(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    try:
        answer = await client.get(url, headers={"accept": "application/json"})
    except httpx.HTTPError as error:
        raise BrandUnavailable(f"{url} could not be reached.") from error
    if answer.status_code != 200:
        raise BrandUnavailable(f"{url} answered {answer.status_code}.")
    return _read(answer)
