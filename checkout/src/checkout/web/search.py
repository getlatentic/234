# SPDX-License-Identifier: AGPL-3.0-or-later
"""Web search through DeepSeek's Search API (docs/web.md): one HTTPS POST with the owner's key as a bearer
token. The request is `query`, `count` and nothing else, so what leaves 234 is the query text.

A result has `title`, `url`, `snippet` (the passage that matched), `summary` (longer, for a model), `date`
(an ISO datetime, null, or the string "None") and scores that 234 does not use."""

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from ..errors import DomainError
from ..transport import Transport, TransportError
from . import safe_url

ENDPOINT = "https://api.deepseek.com/v1/tools/search"
HOST = "api.deepseek.com"
USER_AGENT = "234bot/1.0 (+https://234.getlatentic.com)"
"""Cloudflare in front of the API answers the default client of a Worker's Python with error 1010."""
QUERY_CHARS = 128
"""The longest query the API takes; a longer one is refused outright, so it is cut."""
SNIPPET_CHARS = 500
THIN_SNIPPET_CHARS = 40
MAX_RESULTS = 10
TIMEOUT_SECONDS = 15
_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
UNAVAILABLE = "Web search did not answer. Say so, and do not answer from memory."


@dataclass(frozen=True)
class Hit:
    title: str
    url: str
    snippet: str
    published: str | None


def endpoint_problem(url: str) -> str | None:
    """Why this is not an https address on DeepSeek's API host, or None. The key goes to this address."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if parts.scheme != "https" or parts.hostname != HOST or port not in (None, 443) or parts.username:
        return f"The search address is an https address on {HOST}."
    return None


def _unavailable() -> DomainError:
    return DomainError("SEARCH_UNAVAILABLE", UNAVAILABLE)


def _day(value: object) -> str | None:
    """The ISO day a result was published, when the date says so in that form: the API also says "None"."""
    found = _ISO_DAY.match(str(value or ""))
    return found.group() if found else None


def _snippet(item: dict[str, Any]) -> str:
    """The matching passage, or the start of the summary when the passage is only a fragment."""
    snippet = str(item.get("snippet") or "").strip()
    if len(snippet) >= THIN_SNIPPET_CHARS:
        return snippet[:SNIPPET_CHARS]
    return (str(item.get("summary") or "").strip() or snippet)[:SNIPPET_CHARS]


def hits_of(data: object, limit: int) -> list[Hit]:
    """The results of a reply, without any whose address is not a public https one."""
    items = data.get("results") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise _unavailable()
    found = []
    for item in items:
        url = str(item.get("url", "")) if isinstance(item, dict) else ""
        if safe_url.problem(url) is None:
            found.append(
                Hit(str(item.get("title") or url)[:200], url, _snippet(item), _day(item.get("date")))
            )
    return found[:limit]


class DeepSeekSearch:
    def __init__(self, transport: Transport, api_key: str, url: str = ENDPOINT) -> None:
        self._transport, self._api_key, self._url = transport, api_key, url

    async def search(self, query: str, limit: int) -> list[Hit]:
        limit = max(1, min(limit, MAX_RESULTS))
        body = json.dumps({"query": query[:QUERY_CHARS].rstrip(), "count": limit})
        headers = {
            "authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": USER_AGENT,
        }
        try:
            reply = await self._transport.send(
                "POST", self._url, headers=headers, body=body, timeout_seconds=TIMEOUT_SECONDS
            )
        except TransportError as error:
            raise _unavailable() from error
        if not reply.ok:
            raise _unavailable()
        try:
            data = json.loads(reply.body)
        except ValueError as error:
            raise _unavailable() from error
        return hits_of(data, limit)
