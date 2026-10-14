# SPDX-License-Identifier: AGPL-3.0-or-later
"""Index's list of merchants, read at most once an hour for everyone (`browse_merchants`) and kept in D1. Only
merchants that are `live` or `beta` and that 234 can buy from are kept, and only their id, name, kind and
whether Index asks the person to link them: Index's own description of a merchant ("blurb") is dropped here,
and 234's own words guide the model instead (blurbs.py). The list is read with the asking person's token when
they are connected, and otherwise with the token Index gives 234 itself for its public directory; if neither
can be had, the last list stands."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

from ...clock import Clock
from ...db import Db
from ...errors import DomainError
from ..text import third_party
from .naming import is_index_id, kind_of
from .oauth import IndexOAuth, Registration, Tokens
from .tokens import EARLY_MS, IndexTokens
from .wire import IndexProblem, SessionFactory

TTL_MS = 60 * 60_000
NAME_LIMIT = 80
KEPT_STATUSES = ("live", "beta")
LIST_TOOL = "browse_merchants"
EVERYONE = ""


@dataclass(frozen=True)
class Entry:
    index_id: str
    name: str
    kind: str
    """`food`, `airtime` or `electricity`."""
    code: str | None
    """The network or distribution company Index's purchase tool wants."""
    status: str
    asks_link: bool
    """Index says the person must link this merchant (Chowdeck) before it can be used."""


def entries_of(listed: object) -> list[Entry]:
    """The merchants of a `browse_merchants` answer that 234 keeps."""
    kept = []
    for raw in listed if isinstance(listed, list) else []:
        if not isinstance(raw, dict) or not is_index_id(raw.get("id")):
            continue
        name = third_party(str(raw.get("name") or raw["id"]), NAME_LIMIT)
        bought = kind_of(raw["id"], name, str(raw.get("category", "")))
        status = str(raw.get("status", ""))
        if bought is None or status not in KEPT_STATUSES:
            continue
        asks = bool(raw.get("requires_link")) and raw.get("linked") is not True
        kept.append(Entry(raw["id"], name, bought[0], bought[1], status, asks))
    return kept


class IndexCatalog:
    def __init__(
        self,
        db: Db,
        clock: Clock,
        sessions: SessionFactory,
        tokens: IndexTokens,
        oauth: IndexOAuth,
        registration: Callable[[], Awaitable[Registration]],
    ) -> None:
        self._db, self._clock, self._sessions, self._tokens = db, clock, sessions, tokens
        self._oauth, self._registration = oauth, registration
        self._public: Tokens | None = None

    async def entries(self, reader: str | None = None) -> list[Entry]:
        """The list; `reader` is a connected person whose token may read it if it has to be read again."""
        row = await self._row()
        if row is None or self._clock.now() - row["fetched_at"] >= TTL_MS:
            try:
                await self._refresh(reader)
            except IndexProblem, DomainError:
                pass
            row = await self._row()
        return [Entry(**stored) for stored in json.loads(row["body"])] if row else []

    async def entry(self, index_id: str, reader: str | None = None) -> Entry | None:
        return next((e for e in await self.entries(reader) if e.index_id == index_id), None)

    async def _row(self) -> dict | None:
        return await self._db.row("SELECT body, fetched_at FROM index_catalog WHERE scope = ?", EVERYONE)

    async def _refresh(self, reader: str | None) -> None:
        found = entries_of(await self._listed(reader))
        await self._db.execute(
            "INSERT INTO index_catalog (scope, body, fetched_at) VALUES (?, ?, ?) "
            "ON CONFLICT (scope) DO UPDATE SET body = excluded.body, fetched_at = excluded.fetched_at",
            EVERYONE,
            json.dumps([asdict(entry) for entry in found]),
            self._clock.now(),
        )

    async def _listed(self, reader: str | None) -> object:
        async def read(token: str) -> object:
            reply = await self._sessions(token).call(LIST_TOOL, {"include_coming_soon": False})
            return reply.data.get("merchants")

        if reader is not None:
            return await self._tokens.run(reader, read)
        return await read((await self._public_tokens()).access)

    async def _public_tokens(self) -> Tokens:
        if self._public is None or self._public.expires_at - EARLY_MS <= self._clock.now():
            self._public = await self._oauth.client_credentials(await self._registration())
        return self._public
