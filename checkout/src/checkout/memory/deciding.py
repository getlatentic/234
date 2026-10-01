# SPDX-License-Identifier: AGPL-3.0-or-later
"""The person's decision on a card: Save, No, or Undo. These are the calls only a card makes, each with the
token the card was given. Save is the one way an entry is written; for a recipient it asks the bank again and
saves only when the bank still gives the name the card showed."""

from typing import Any

from ..errors import DomainError
from ..flows.bank_choice import choose_bank
from ..flows.holder import account_holder
from .context import MemoryContext
from .fields import clean_name
from .never_store import assert_storable
from .proposals import APPLIED, DISCARDED, FORGET, PENDING, REMEMBER, UNDONE, Proposal
from .recipient import same_name
from .view import DISCARDED as VIEW_DISCARDED
from .view import EXPIRED, REFUSED, RESTORED, SAVED, proposal_view

STATE_VIEWS = {APPLIED: SAVED, DISCARDED: VIEW_DISCARDED, UNDONE: RESTORED}
NAME_CHANGED = "The bank now gives a different name for this account, so nothing was saved."


def _denied() -> DomainError:
    return DomainError("MEMORY_DENIED", "Only the card the person is looking at can decide on this note.")


class Deciding:
    def __init__(self, ctx: MemoryContext) -> None:
        self._ctx = ctx

    async def _load(self, owner: str, proposal_id: str, token: str) -> Proposal:
        if not self._ctx.proposals.token_is_valid(owner, proposal_id, token):
            self._ctx.audit.log("memory.denied", proposal=proposal_id)
            raise _denied()
        proposal = await self._ctx.proposals.get(owner, proposal_id)
        if proposal is None:
            raise DomainError("MEMORY_NOT_FOUND", "There is no such request. It may be old; ask again.")
        return proposal

    def _view(self, proposal: Proposal, state: str, note: str = "") -> dict[str, Any]:
        return proposal_view(proposal.id, proposal.op, state, proposal.payload, note)

    async def confirm(self, owner: str, proposal_id: str, token: str) -> dict[str, Any]:
        proposal = await self._load(owner, proposal_id, token)
        if proposal.op == FORGET:
            raise DomainError("MEMORY_INVALID", "A forget is already done. Use undo to bring it back.")
        if proposal.state != PENDING:
            return self._view(proposal, STATE_VIEWS.get(proposal.state, VIEW_DISCARDED))
        if proposal.expired(self._ctx.clock.now()):
            await self._ctx.proposals.discard(owner, proposal.id)
            return self._view(proposal, EXPIRED, "This request has expired.")
        if refusal := await self._unfit(proposal):
            await self._ctx.proposals.discard(owner, proposal.id)
            return self._view(proposal, REFUSED, refusal)
        return await self._apply(owner, proposal)

    async def _unfit(self, proposal: Proposal) -> str | None:
        """Why the proposal cannot be saved as it stands, or None: the text is checked again, and a
        recipient's account is looked up again."""
        payload = proposal.payload
        assert_storable(payload["kind"], payload["title"], payload["hook"], payload["body"])
        if payload["kind"] != "recipient":
            return None
        chosen = choose_bank(payload["bank_name"], payload["bank_code"])
        name = clean_name(await account_holder(self._ctx.paystack, payload["account_number"], chosen.code))
        return None if same_name(name, payload["account_name"]) else NAME_CHANGED

    async def _apply(self, owner: str, proposal: Proposal) -> dict[str, Any]:
        if await self._ctx.proposals.apply(owner, proposal):
            await self._ctx.store.purge()
            kind = "memory.saved" if proposal.op == REMEMBER else "memory.changed"
            self._ctx.audit.log(
                kind, kind_of=proposal.payload["kind"], entry=proposal.target_id or proposal.id
            )
            return self._view(proposal, SAVED)
        current = await self._ctx.proposals.get(owner, proposal.id)
        if current is not None and current.state != PENDING:
            return self._view(current, STATE_VIEWS.get(current.state, VIEW_DISCARDED))
        raise DomainError(
            "MEMORY_FULL",
            "Memory is full, so nothing was saved. Forget a note first, then ask again.",
        )

    async def discard(self, owner: str, proposal_id: str, token: str) -> dict[str, Any]:
        proposal = await self._load(owner, proposal_id, token)
        if proposal.op == FORGET:
            raise DomainError("MEMORY_INVALID", "A forget is not a proposal. Use undo.")
        await self._ctx.proposals.discard(owner, proposal.id)
        current = await self._ctx.proposals.get(owner, proposal.id) or proposal
        return self._view(current, STATE_VIEWS.get(current.state, VIEW_DISCARDED))

    async def undo(self, owner: str, proposal_id: str, token: str) -> dict[str, Any]:
        proposal = await self._load(owner, proposal_id, token)
        if proposal.op != FORGET:
            raise DomainError("MEMORY_INVALID", "Only a forget can be undone.")
        if proposal.state == UNDONE:
            return self._view(proposal, RESTORED)
        if not await self._ctx.proposals.undo_forget(owner, proposal):
            raise DomainError(
                "MEMORY_GONE", "That note can no longer be brought back: it was forgotten too long ago."
            )
        self._ctx.audit.log("memory.restored", entry=proposal.target_id)
        return self._view(proposal, RESTORED)
