# SPDX-License-Identifier: AGPL-3.0-or-later
"""The client 234 is at Index's authorization server. It registers itself once for a deployment (RFC 7591) for
the redirect address the chat host serves, and every person who connects uses that one client. Two calls that
register together leave one stored; the other client is never used."""

from .oauth import IndexOAuth, Registration
from .store import IndexStore


class Registrations:
    def __init__(self, store: IndexStore, oauth: IndexOAuth, server: str, redirect_uri: str) -> None:
        self._store, self._oauth, self._server, self._redirect = store, oauth, server, redirect_uri

    async def current(self) -> Registration:
        found = await self._store.registration(self._server, self._redirect)
        if found is not None:
            return found
        made = await self._oauth.register(self._redirect)
        await self._store.keep_registration(self._server, self._redirect, made)
        return await self._store.registration(self._server, self._redirect) or made
