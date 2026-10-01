# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a person does with their own notes in the page: see them, change a title or a hook in place, delete
one (with an Undo), take a copy, or delete everything. The host calls these for a signed-in account; no model
does. Each is the person's own act, so none needs a card."""

from typing import Any

from ..errors import DomainError
from .context import MemoryContext
from .fields import clean_hook, clean_title
from .never_store import assert_storable
from .proposing import Proposing


class Account:
    def __init__(self, ctx: MemoryContext) -> None:
        self._ctx = ctx

    async def entries(self, owner: str) -> dict[str, Any]:
        live = await self._ctx.store.live(owner)
        limit = self._ctx.store.settings.max_entries
        return {
            "entries": [entry.for_owner() | {"has_account": bool(entry.account_number)} for entry in live],
            "limit": limit,
        }

    async def edit(self, owner: str, entry_id: str, title: str | None, hook: str | None) -> dict[str, Any]:
        entry = await self._ctx.store.require(owner, entry_id)
        new_title = clean_title(title) if title is not None else entry.title
        new_hook = entry.hook
        if hook is not None:
            if entry.kind == "recipient":
                raise DomainError(
                    "MEMORY_INVALID", "A recipient's line is the bank's own words; change the title."
                )
            new_hook = clean_hook(hook)
        if taken := await self._ctx.store.title_taken(owner, entry.kind, new_title, entry.id):
            raise DomainError("MEMORY_INVALID", f'Another note is already titled "{new_title}" (id {taken}).')
        assert_storable(entry.kind, new_title, new_hook, entry.body)
        await self._ctx.store.edit(owner, entry.id, new_title, new_hook)
        return {"id": entry.id, "title": new_title, "hook": new_hook}

    async def forget(self, owner: str, entry_id: str) -> dict[str, Any]:
        proposed = await Proposing(self._ctx).forget(owner, entry_id)
        return {
            "proposal_id": proposed.proposal.id,
            "token": proposed.token,
            "title": proposed.proposal.payload["title"],
        }

    async def export(self, owner: str) -> dict[str, Any]:
        live = await self._ctx.store.live(owner)
        return {"exported_at": self._ctx.clock.now(), "entries": [entry.for_owner() for entry in live]}

    async def delete_everything(self, owner: str) -> dict[str, Any]:
        deleted = await self._ctx.store.delete_everything(owner)
        self._ctx.audit.log("memory.deleted_everything", entries=deleted)
        return {"deleted": deleted}
