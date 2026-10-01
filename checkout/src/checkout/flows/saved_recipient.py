# SPDX-License-Identifier: AGPL-3.0-or-later
"""A transfer to a recipient the person saved. The model names the recipient by id and never gives digits for
it: the account and the bank are read here, from the owner's own notes, and the bank is asked again for the
name, which must still be the name the person saved."""

from ..errors import DomainError
from ..memory.entry import Entry
from ..memory.recipient import same_name
from .context import Context


async def saved_recipient(
    ctx: Context, memory_id: str | None, account_number: str | None, bank: str | None, bank_code: str | None
) -> Entry | None:
    """The saved recipient a call names, or None when it names an account itself. A call that does both is
    refused, as is an id that is not a recipient of the caller."""
    if memory_id is None:
        if account_number is None:
            raise DomainError(
                "INVALID_INPUT",
                "Say who to send to: a saved recipient's recipient_memory_id, or account_number and bank.",
            )
        return None
    if any(value is not None for value in (account_number, bank, bank_code)):
        raise DomainError(
            "INVALID_INPUT",
            "A saved recipient is used by recipient_memory_id alone: pass no account number and no bank.",
        )
    entry = await ctx.memory.get(ctx.ledger.owner(), memory_id) if ctx.memory else None
    if entry is None or entry.kind != "recipient":
        raise DomainError(
            "RECIPIENT_NOT_FOUND",
            "There is no saved recipient with that id. Nothing was quoted. "
            "Ask the person for the account number and the bank.",
        )
    return entry


def assert_same_holder(ctx: Context, saved: Entry, name: str) -> None:
    if not same_name(name, saved.account_name or ""):
        ctx.audit.log("recipient.name_changed", entry=saved.id)
        raise DomainError(
            "RECIPIENT_NAME_CHANGED",
            f'The bank now gives "{name}" for the account saved as "{saved.title}"; it was saved as '
            f'"{saved.account_name}". Nothing was quoted. Tell the person, and ask them to check the '
            "account and say its number and bank again.",
        )
