# SPDX-License-Identifier: AGPL-3.0-or-later
"""Streaming chat completions from an OpenAI-compatible endpoint, over async httpx.

The request carries `tool_choice: "auto"` (an endpoint that does not default to it may never call a
tool) and a low reasoning effort, and no output ceiling: reasoning expands to fill any budget it is
given. What the model stopped for (`finish_reason`) and, when the endpoint reports it, what the request
cost in tokens (`usage`, asked for with `stream_options`) are returned with every reply.
"""

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from .settings import Settings

CONTEXT_REFUSAL = re.compile(
    r"context[ _-]?(?:length|window)|too long|too many tokens|maximum.{0,40}tokens"
    r"|exceeds? .{0,40}(?:limit|tokens)",
    re.IGNORECASE,
)


TRANSIENT_STATUSES = frozenset(
    {408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 529, 530}
)
TRANSIENT_BODY = re.compile(
    r"rate[ _-]?limit|throttl|overloaded|unavailable|temporar|try again", re.IGNORECASE
)


class ModelError(Exception):
    """`transient`: asking again soon may succeed (the endpoint is busy or could not be reached), unlike a
    refusal of the request itself."""

    def __init__(self, message: str = "", transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class ContextTooLong(ModelError):
    """The endpoint refused the request because it did not fit the model's context."""


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Finished:
    reason: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] | None = None


class Model(Protocol):
    def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[TextDelta | Finished]: ...


def request_body(
    settings: Settings, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
) -> dict[str, Any]:
    body: dict[str, Any] = {"model": settings.llm_model, "messages": messages, "stream": True}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if settings.reasoning_effort != "off":
        body["reasoning_effort"] = settings.reasoning_effort
    if settings.stream_usage:
        body["stream_options"] = {"include_usage": True}
    return body


def _usage_of(chunk: dict[str, Any]) -> dict[str, int] | None:
    usage = chunk.get("usage")
    if not isinstance(usage, dict):
        return None
    return {
        name: int(usage[name])
        for name in ("prompt_tokens", "completion_tokens")
        if isinstance(usage.get(name), int)
    } or None


def _refused(status: int | None, body: str) -> ModelError:
    """The error for a request the endpoint did not accept: as an HTTP status or, as the Bedrock endpoint does
    when the prompt is too long, as an error event in a stream that began with 200. The message is plain and
    names neither a URL nor the body."""
    what = (
        f"The model endpoint answered HTTP {status}." if status else "The model endpoint reported an error."
    )
    too_long = status in (None, 400, 413) and CONTEXT_REFUSAL.search(body[:4000])
    if too_long:
        return ContextTooLong(what)
    busy = status in TRANSIENT_STATUSES or (status is None and TRANSIENT_BODY.search(body[:4000]))
    return ModelError(what, transient=bool(busy))


def _accumulate(calls: dict[int, dict[str, Any]], pieces: list[dict[str, Any]]) -> None:
    for piece in pieces:
        call = calls.setdefault(piece.get("index", 0), {"id": "", "name": "", "arguments": ""})
        call["id"] = piece.get("id") or call["id"]
        function = piece.get("function", {})
        call["name"] += function.get("name") or ""
        call["arguments"] += function.get("arguments") or ""


class OpenAICompatible:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[TextDelta | Finished]:
        if problem := self._settings.model_problem():
            raise ModelError(problem)
        calls: dict[int, dict[str, Any]] = {}
        reason, usage = "stop", None
        try:
            async with self._client.stream(
                "POST",
                f"{self._settings.llm_base_url.rstrip('/')}/chat/completions",
                json=request_body(self._settings, messages, tools),
                headers={"authorization": f"Bearer {self._settings.llm_api_key}"},
                timeout=self._settings.llm_timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    raise _refused(response.status_code, (await response.aread()).decode(errors="replace"))
                async for line in response.aiter_lines():
                    if not line.startswith("data:") or line.strip() == "data: [DONE]":
                        continue
                    chunk = json.loads(line[5:])
                    if isinstance(chunk.get("error"), dict):
                        raise _refused(None, json.dumps(chunk["error"]))
                    usage = _usage_of(chunk) or usage
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta", {})
                        if delta.get("content"):
                            yield TextDelta(delta["content"])
                        _accumulate(calls, delta.get("tool_calls") or [])
                        reason = choice.get("finish_reason") or reason
        except httpx.HTTPError as error:
            raise ModelError(
                f"The model could not be reached: {error.__class__.__name__}.", transient=True
            ) from error
        yield Finished(reason, [calls[i] for i in sorted(calls)], usage)
