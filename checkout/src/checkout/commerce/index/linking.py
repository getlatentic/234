# SPDX-License-Identifier: AGPL-3.0-or-later
"""Linking Chowdeck at Index from the connect card (Index's `connect_merchant`): the person types the phone
number of their Chowdeck account into the card, Index texts a code to it, and they type the code into the
card. Both go from the card to this server and from here to Index; neither is in a tool the model calls, in a
result the model reads, or in a log. Whether the link worked is learnt from Index itself: after the code, a
read of Chowdeck's nearby feed succeeds only for a linked account."""

import re

from ...errors import DomainError
from ...vtpass.phone import normalise_phone
from .attempts import Attempt, Attempts
from .reading import words
from .store import IndexStore
from .tokens import IndexTokens
from .wire import IndexProblem, SessionFactory

_CODE = re.compile(r"[A-Za-z0-9]{4,10}")
TOO_MANY = DomainError(
    "LINK_TRIES", "That is too many tries for one card. Close it and ask for the connection again."
)


def international(phone: str) -> str:
    """The phone as Index wants it (+234...), from any way a Nigerian number is written."""
    return "+234" + normalise_phone(phone)[1:]


class Linking:
    def __init__(
        self, attempts: Attempts, tokens: IndexTokens, sessions: SessionFactory, store: IndexStore
    ) -> None:
        self._attempts, self._tokens, self._sessions, self._store = attempts, tokens, sessions, store

    async def _call(self, owner: str, tool: str, arguments: dict[str, str]):
        async def work(token: str):
            return await self._sessions(token).call(tool, arguments)

        try:
            return await self._tokens.run(owner, work)
        except IndexProblem as problem:
            raise DomainError(
                "INDEX_UNAVAILABLE", "Paystack Index did not answer. Try again in a moment."
            ) from problem

    async def send_code(self, owner: str, attempt: Attempt, merchant: str, phone: str) -> None:
        number = international(phone)
        if not await self._attempts.count_try(owner, attempt.id):
            raise TOO_MANY
        reply = await self._call(owner, "connect_merchant", {"merchant_id": merchant, "phone": number})
        if reply.is_error:
            raise DomainError(
                "CODE_NOT_SENT", f"Paystack Index could not send a code: {words(reply.text, 120)}"
            )
        await self._attempts.advance(owner, attempt.id, "code")

    async def confirm(self, owner: str, attempt: Attempt, merchant: str, phone: str, code: str) -> None:
        number = international(phone)
        if not _CODE.fullmatch(code.strip()):
            raise DomainError("CODE_INVALID", "The code is 4 to 10 letters or digits, as it was texted.")
        if not await self._attempts.count_try(owner, attempt.id):
            raise TOO_MANY
        reply = await self._call(
            owner, "connect_merchant", {"merchant_id": merchant, "phone": number, "otp": code.strip()}
        )
        if reply.is_error or not await self._is_linked(owner, merchant):
            raise DomainError(
                "CODE_REFUSED", "Paystack Index did not accept that code. Check it and try again."
            )
        await self._store.link(owner, merchant)
        await self._attempts.advance(owner, attempt.id, "done")

    async def _is_linked(self, owner: str, merchant: str) -> bool:
        probe = await self._call(owner, "find_items", {"merchant_id": merchant, "limit": 1})
        return not probe.is_error
