# SPDX-License-Identifier: AGPL-3.0-or-later
"""Placing an approved quote's order with Index: the one place a call that charges (`confirmed`) is made.

The send is at most once. Before the call is sent a marker is written once for the quote (`set_progress_once`,
one conditional UPDATE); a call that finds it already written does not send, it asks where the order stands
(following.py). So a repeated approval, a crash between the send and the answer, and the minute's recheck can
never charge twice. Anything that happens before the marker means nothing was sent: the person is not
connected, Index refused the token, or a Chowdeck order's price moved since the quote. After it, a reply
decides (outcomes.py), and no reply at all is pending."""

from ...audit import Audit
from ...clock import Clock
from ...errors import DomainError
from ...ledger import Ledger, Quote
from ..model import Outcome
from .following import WINDOW_MS, follow
from .kind_food import previewed_total
from .outcomes import placed
from .purchase import Preview, Purchase
from .tokens import IndexTokens
from .wire import IndexMisread, IndexProblem, IndexRefused, IndexUnreachable, SessionFactory

SENT = "indexSend"
ASKED = (
    "Paystack Index did not answer after 234 sent the order, so it may have gone through. 234 will not send "
    "it "
    "again; it asks Index and the person's Zap history until it knows."
)
NOT_SENT = "Nothing was sent to Paystack Index, so nothing was charged: {why}"
PRICE_MOVED = "Chowdeck's price for this order changed after the quote was made. Ask for a new quote."


def first_sentence(text: str) -> str:
    return text.split(". ")[0].rstrip(".") + "."


class IndexFulfilment:
    def __init__(
        self, ledger: Ledger, tokens: IndexTokens, sessions: SessionFactory, clock: Clock, audit: Audit
    ) -> None:
        self._ledger, self._tokens, self._sessions = ledger, tokens, sessions
        self._clock, self._audit = clock, audit

    async def fulfil(self, quote: Quote) -> Outcome:
        owner = self._ledger.owner()
        if early := await self._not_ready(quote, owner):
            return early
        if not await self._ledger.set_progress_once(quote.id, SENT, {"at": self._clock.now()}):
            return await self.status(quote)
        self._audit.log("index.send", quote=quote.id, tool=quote.details["index"]["tool"])
        return await self._send(quote, owner)

    async def _not_ready(self, quote: Quote, owner: str) -> Outcome | None:
        """An outcome when the order cannot be sent now, because nothing has been sent: the person is not
        connected, the price moved, or Index could not be asked (pending, until an hour after the
        approval)."""
        purchase = Purchase.from_terms(quote.details["index"])
        try:
            await self._tokens.usable(owner)
            if purchase.kind == "food" and await self._moved(purchase, owner) != quote.amount_kobo:
                return Outcome("failed", NOT_SENT.format(why=PRICE_MOVED))
        except DomainError as problem:
            return Outcome("failed", NOT_SENT.format(why=first_sentence(problem.message)))
        except IndexProblem as problem:
            late = self._clock.now() - (quote.approved_at or quote.created_at) >= WINDOW_MS
            return Outcome(
                "failed" if late else "pending", NOT_SENT.format(why=f"{first_sentence(str(problem))}")
            )
        return None

    async def _moved(self, purchase: Purchase, owner: str) -> int:
        async def work(token: str) -> int:
            return await previewed_total(Preview(self._sessions(token)), purchase.arguments)

        return await self._tokens.run(owner, work)

    async def _send(self, quote: Quote, owner: str) -> Outcome:
        purchase = Purchase.from_terms(quote.details["index"])

        async def work(token: str):
            return await self._sessions(token).call(purchase.tool, purchase.confirmed_arguments())

        try:
            reply = await self._tokens.run(owner, work)
        except IndexUnreachable, IndexMisread:
            self._audit.log("index.unconfirmed", quote=quote.id)
            return Outcome("pending", ASKED)
        except (IndexRefused, DomainError) as problem:
            why = problem.message if isinstance(problem, DomainError) else str(problem)
            return Outcome("failed", NOT_SENT.format(why=first_sentence(why)))
        return placed(purchase, reply)

    async def status(self, quote: Quote) -> Outcome:
        """Asks Index where the order stands. An order that was never sent is sent now: nothing was ever
        charged for it."""
        sent = (await self._ledger.require(quote.id, quote.connector)).progress.get(SENT)
        if sent is None:
            return await self.fulfil(quote)

        async def work(token: str) -> Outcome:
            return await follow(self._sessions(token), quote, sent["at"], self._clock.now())

        try:
            return await self._tokens.run(self._ledger.owner(), work)
        except IndexUnreachable, IndexMisread, IndexRefused:
            return Outcome("pending", ASKED)
        except DomainError as problem:
            return Outcome("pending", f"234 cannot ask Paystack Index now: {first_sentence(problem.message)}")
