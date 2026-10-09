# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reads a web page for the model (docs/web.md): an https address by public name, not on the deny list, that
the site's robots.txt allows; at most three redirects, each checked again; at most 2 MB; HTML as text
clipped to about 6,000 tokens; kept for an hour."""

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from ..clock import Clock
from ..errors import DomainError
from . import robots, safe_url
from .cache import Entry, WebCache
from .extract import text_of
from .fetcher import Fetched, Fetcher, FetchFailed

MAX_REDIRECTS = 3
MAX_BYTES = 2_000_000
MAX_CHARS = 24_000
ROBOTS_BYTES = 512_000
TIMEOUT_SECONDS = 10
USER_AGENT = "234bot/1.0 (+https://234.getlatentic.com)"
HTML_TYPES = ("text/html", "application/xhtml+xml")
TEXT_TYPES = (*HTML_TYPES, "text/plain")
REDIRECTS = (301, 302, 303, 307, 308)
DEFAULT_DENY = ("workers.dev",)
_CHARSET = re.compile(r"charset=([\w-]+)", re.IGNORECASE)


@dataclass(frozen=True)
class Policy:
    enabled: bool = True
    deny: tuple[str, ...] = DEFAULT_DENY


@dataclass(frozen=True)
class Page:
    url: str
    final_url: str
    title: str
    text: str
    truncated: bool
    fetched_at: int
    cached: bool


class WebReader:
    def __init__(self, fetcher: Fetcher, cache: WebCache, clock: Clock, policy: Policy) -> None:
        self._fetcher, self._cache, self._clock, self._policy = fetcher, cache, clock, policy

    async def read(self, url: str) -> Page:
        self._allowed(url)
        cached = await self._cache.get(url, "page")
        entry = cached or await self._fetch_page(url)
        if cached is None:
            await self._cache.put(url, "page", entry)
        return Page(
            url, entry.final_url, entry.title, entry.text, entry.truncated, entry.fetched_at, bool(cached)
        )

    def _allowed(self, url: str) -> None:
        if not self._policy.enabled:
            raise DomainError("WEB_OFF", "Reading web pages is switched off.")
        if why := safe_url.problem(url):
            raise DomainError("BAD_ADDRESS", why)
        if safe_url.under(urlsplit(url).hostname or "", self._policy.deny):
            raise DomainError("DENIED", "That site cannot be read.")

    async def _fetch_page(self, url: str) -> Entry:
        final, got = await self._chase(url, check_robots=True, max_bytes=MAX_BYTES)
        return self._entry(final, got)

    async def _chase(self, url: str, *, check_robots: bool, max_bytes: int) -> tuple[str, Fetched]:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            self._allowed(current)
            if check_robots:
                await self._robots(current)
            got = await self._get(current, max_bytes)
            location = got.headers.get("location")
            if got.status not in REDIRECTS or not location:
                return current, got
            current = urljoin(current, location)
        raise DomainError("TOO_MANY_REDIRECTS", f"The page redirects more than {MAX_REDIRECTS} times.")

    async def _get(self, url: str, max_bytes: int) -> Fetched:
        try:
            return await self._fetcher.get(
                url,
                headers={"user-agent": USER_AGENT, "accept": "text/html,text/plain;q=0.9"},
                timeout_seconds=TIMEOUT_SECONDS,
                max_bytes=max_bytes,
            )
        except FetchFailed as error:
            raise DomainError("UNREACHABLE", "The site did not answer.") from error

    async def _robots(self, url: str) -> None:
        parts = urlsplit(url)
        address = f"https://{parts.hostname}/robots.txt"
        entry = await self._cache.get(address, "robots")
        if entry is None:
            final, got = await self._chase(address, check_robots=False, max_bytes=ROBOTS_BYTES)
            text = "" if got.too_large else got.body.decode("utf-8", "replace")
            entry = Entry(got.status, final, "", text, False, self._clock.now())
            await self._cache.put(address, "robots", entry)
        if not robots.allows(entry.status, entry.text, url):
            raise DomainError("ROBOTS", "The site asks robots not to read that page.")

    def _entry(self, final_url: str, got: Fetched) -> Entry:
        kind = got.headers.get("content-type", "")
        base = kind.split(";")[0].strip().lower()
        if got.status >= 400:
            raise DomainError("PAGE_UNAVAILABLE", f"The site answered {got.status}.")
        if got.too_large:
            raise DomainError("TOO_LARGE", "The page is larger than 2 MB.")
        if base not in TEXT_TYPES:
            raise DomainError("UNSUPPORTED_TYPE", "Only web pages and plain text can be read.")
        found = _CHARSET.search(kind)
        body = got.body.decode(found.group(1) if found else "utf-8", "replace")
        title, text = text_of(body) if base in HTML_TYPES else ("", body.strip())
        return Entry(got.status, final_url, title, text[:MAX_CHARS], len(text) > MAX_CHARS, self._clock.now())
