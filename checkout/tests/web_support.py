# SPDX-License-Identifier: AGPL-3.0-or-later
"""A web that answers from a table: `Web.at(url)` says what a GET of it returns, and every GET is kept."""

from collections.abc import Mapping

from checkout.web.fetcher import Fetched, FetchFailed

HTML = "text/html; charset=utf-8"


def page(body: str, kind: str = HTML, status: int = 200, **headers: str) -> Fetched:
    return Fetched(status, {"content-type": kind, **headers}, body.encode())


def redirect(to: str, status: int = 302) -> Fetched:
    return Fetched(status, {"location": to})


class Web:
    def __init__(self, **sites: Fetched | Exception) -> None:
        self.table: dict[str, Fetched | Exception] = {}
        self.gets: list[str] = []
        self.max_bytes: list[int] = []
        for url, answer in sites.items():
            self.table[url] = answer

    def at(self, url: str, answer: Fetched | Exception) -> Web:
        self.table[url] = answer
        return self

    async def get(
        self, url: str, *, headers: Mapping[str, str], timeout_seconds: float, max_bytes: int
    ) -> Fetched:
        self.gets.append(url)
        self.max_bytes.append(max_bytes)
        answer = self.table.get(url, Fetched(404, {"content-type": "text/plain"}, b"not here"))
        if isinstance(answer, Exception):
            raise answer
        if len(answer.body) > max_bytes:
            return Fetched(answer.status, answer.headers, b"", True)
        return answer

    def pages(self) -> list[str]:
        return [u for u in self.gets if not u.endswith("/robots.txt")]


UNREACHABLE = FetchFailed("timed out")
