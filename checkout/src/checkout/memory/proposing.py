# SPDX-License-Identifier: AGPL-3.0-or-later
"""The model's way to change memory: it proposes, the person decides. Each call here validates what the model
sent, asks the bank about a recipient, and makes a proposal with a card to show it. None writes an entry
(`Proposals.apply` does, when the person presses Save), except `forget`, which hides an entry at once and
gives the person an Undo."""

from dataclasses import dataclass
from typing import Any

from ..errors import DomainError
from .context import MemoryContext
from .entry import KINDS, SOURCE_BY_KIND, Entry
from .fields import clean_body, clean_hook, clean_title
from .never_store import assert_storable
from .proposals import APPLIED, FORGET, REMEMBER, UPDATE, Proposal
from .recipient import Holder, resolve_holder
from .view import FORGOTTEN, PENDING, proposal_view


@dataclass(frozen=True)
class Proposed:
    """A proposal the person is to decide on: the card's view and token, and what the model is told."""

    proposal: Proposal
    view: dict[str, Any]
    token: str
    text: str


def invalid(message: str) -> DomainError:
    return DomainError("MEMORY_INVALID", message)


def full() -> DomainError:
    return DomainError(
        "MEMORY_FULL",
        "Memory is full. Nothing was saved. Ask the person which note to forget, then forget it.",
    )


class Proposing:
    def __init__(self, ctx: MemoryContext) -> None:
        self._ctx = ctx

    async def remember(
        self,
        owner: str,
        *,
        kind: str,
        title: str,
        hook: str | None = None,
        body: str | None = None,
        account_number: str | None = None,
        bank: str | None = None,
    ) -> Proposed:
        store = self._ctx.store
        if kind not in KINDS:
            raise invalid(f"kind is one of {', '.join(KINDS)}.")
        if await store.count_live(owner) >= store.settings.max_entries:
            raise full()
        clean = clean_title(title)
        if taken := await store.title_taken(owner, kind, clean):
            raise invalid(
                f'A {kind} titled "{clean}" is already saved (id {taken}). Use update with that id.'
            )
        payload = await self._content(kind, clean, hook, body, account_number, bank)
        proposal = await self._ctx.proposals.create(owner, REMEMBER, None, payload)
        return self._proposed(owner, proposal, f"Proposed to remember {_summary(payload)}.")

    async def update(
        self,
        owner: str,
        entry_id: str,
        *,
        title: str | None = None,
        hook: str | None = None,
        body: str | None = None,
        account_number: str | None = None,
        bank: str | None = None,
    ) -> Proposed:
        entry = await self._ctx.store.require(owner, entry_id)
        new_title = clean_title(title) if title is not None else entry.title
        if taken := await self._ctx.store.title_taken(owner, entry.kind, new_title, entry.id):
            raise invalid(f'Another {entry.kind} is already titled "{new_title}" (id {taken}).')
        payload = await self._changed(entry, new_title, hook, body, account_number, bank)
        if _same_content(entry, payload):
            raise invalid("Nothing would change. Say what to change.")
        proposal = await self._ctx.proposals.create(owner, UPDATE, entry.id, payload)
        return self._proposed(owner, proposal, f"Proposed to change {_summary(payload)}.")

    async def forget(self, owner: str, entry_id: str) -> Proposed:
        entry = await self._ctx.store.require(owner, entry_id)
        await self._ctx.store.forget(owner, entry.id)
        payload = {"kind": entry.kind, "title": entry.title, "hook": entry.hook}
        proposal = await self._ctx.proposals.create(owner, FORGET, entry.id, payload, APPLIED)
        await self._ctx.store.purge()
        self._ctx.audit.log("memory.forgotten", kind=entry.kind, entry=entry.id)
        text = f'Forgot "{entry.title}". The person can undo it on the card.'
        return self._shown(owner, proposal, FORGOTTEN, text)

    async def _content(
        self, kind: str, title: str, hook: str | None, body: str | None, account: str | None, bank: str | None
    ) -> dict[str, Any]:
        max_bytes = self._ctx.store.settings.max_body_bytes
        if kind == "recipient":
            holder = await self._holder(account, bank)
            text = clean_body(body or "", max_bytes, required=False)
            assert_storable(kind, title, holder.hook, text)
            return _recipient_payload(title, text, holder)
        if account is not None or bank is not None:
            raise invalid("account_number and bank are for a recipient only.")
        if hook is None or body is None:
            raise invalid(f"A {kind} needs a hook (one line) and a body.")
        clean_line, text = clean_hook(hook), clean_body(body, max_bytes)
        assert_storable(kind, title, clean_line, text)
        return {
            "kind": kind,
            "title": title,
            "hook": clean_line,
            "body": text,
            "source": SOURCE_BY_KIND[kind],
        }

    async def _changed(
        self,
        entry: Entry,
        title: str,
        hook: str | None,
        body: str | None,
        account: str | None,
        bank: str | None,
    ) -> dict[str, Any]:
        max_bytes = self._ctx.store.settings.max_body_bytes
        text = (
            clean_body(body, max_bytes, required=entry.kind != "recipient")
            if body is not None
            else entry.body
        )
        if entry.kind == "recipient":
            holder = await self._holder(account, bank) if (account or bank) else _held(entry)
            assert_storable(entry.kind, title, holder.hook, text)
            return _recipient_payload(title, text, holder)
        if account is not None or bank is not None:
            raise invalid("account_number and bank are for a recipient only.")
        line = clean_hook(hook) if hook is not None else entry.hook
        assert_storable(entry.kind, title, line, text)
        return {"kind": entry.kind, "title": title, "hook": line, "body": text, "source": entry.source}

    async def _holder(self, account: str | None, bank: str | None) -> Holder:
        if not account or not bank:
            raise invalid("A recipient needs account_number and bank, as the person said them.")
        return await resolve_holder(self._ctx.paystack, account, bank)

    def _proposed(self, owner: str, proposal: Proposal, text: str) -> Proposed:
        suffix = " Nothing is saved until the person presses Save on the card. Do not say it is saved."
        return self._shown(owner, proposal, PENDING, text + suffix)

    def _shown(self, owner: str, proposal: Proposal, state: str, text: str) -> Proposed:
        view = proposal_view(proposal.id, proposal.op, state, proposal.payload)
        return Proposed(proposal, view, self._ctx.proposals.token(owner, proposal.id), text)


def _recipient_payload(title: str, body: str, holder: Holder) -> dict[str, Any]:
    return {
        "kind": "recipient",
        "title": title,
        "hook": holder.hook,
        "body": body,
        "source": SOURCE_BY_KIND["recipient"],
        "bank_name": holder.bank_name,
        **holder.fields(),
    }


def _held(entry: Entry) -> Holder:
    assert entry.account_number and entry.bank_code and entry.account_name
    return Holder(
        entry.account_number, entry.bank_code, entry.bank_name or entry.bank_code, entry.account_name
    )


def _same_content(entry: Entry, payload: dict[str, Any]) -> bool:
    keys = ("title", "hook", "body", "bank_code", "account_number", "account_name")
    return all(payload.get(key) == getattr(entry, key) for key in keys)


def _summary(payload: dict[str, Any]) -> str:
    if payload["kind"] == "recipient":
        return f'the recipient "{payload["title"]}" ({payload["hook"]})'
    return f'the {payload["kind"]} "{payload["title"]}": {payload["hook"]}'
