# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `index` provider (docs/commerce.md): merchants from the directory of a person's own Paystack Index
account, priced by Index's own previews, placed by Index only after the person approves the quote's card.
Only a signed-in account has any of it; for anyone else Index lists no merchant. The model never meets Index's
tools: this class is the one place that calls them, with a token only the owner's connection can give."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace

from ...errors import DomainError
from ...ledger import Ledger, Quote
from ...wallet.access import account_of_call
from ..model import AccountCheck, Basket, Merchant, Offer, Outcome, Totals
from ..provider import AccountLookup
from . import kind_airtime, kind_electricity, kind_food
from .catalog import Entry, IndexCatalog
from .fulfil import IndexFulfilment
from .merchants import merchant_of
from .naming import index_id_of
from .purchase import NotLinked, Preview
from .reading import words
from .settings import IndexSettings
from .store import Connection, IndexStore
from .tokens import IndexTokens, not_connected
from .wire import IndexMisread, IndexProblem, IndexUnreachable, SessionFactory

NAME = "index"


def refusal_of(problem: IndexProblem) -> DomainError:
    """What the model and the person are told when Index could not be asked or would not answer. The order
    was only being priced, so nothing was charged."""
    if isinstance(problem, IndexUnreachable):
        return DomainError(
            "INDEX_UNAVAILABLE", "Paystack Index did not answer. Nothing was charged. Try again in a moment."
        )
    if isinstance(problem, IndexMisread):
        return DomainError(
            "INDEX_UNREADABLE", "Paystack Index answered in a way 234 cannot read, so nothing was quoted."
        )
    detail = words(str(problem), 120)
    return DomainError("INDEX_REFUSED", f"Paystack Index refused: {detail}. Nothing was charged.")


class IndexProvider:
    name = NAME

    def __init__(
        self,
        catalog: IndexCatalog,
        store: IndexStore,
        tokens: IndexTokens,
        sessions: SessionFactory,
        fulfilment: IndexFulfilment,
        settings: IndexSettings,
        ledger: Ledger,
    ) -> None:
        self._catalog, self._store, self._tokens = catalog, store, tokens
        self._sessions, self._fulfilment, self._settings, self._ledger = (
            sessions,
            fulfilment,
            settings,
            ledger,
        )

    async def _connection(self) -> Connection | None:
        return await self._store.connection(self._ledger.owner()) if account_of_call() else None

    async def connected(self) -> bool:
        """Whether the acting account has an Index connection now."""
        return await self._connection() is not None

    async def merchants(self, category: str | None = None) -> list[Merchant]:
        if account_of_call() is None:
            return []
        connection = await self._connection()
        entries = await self._catalog.entries(connection.owner if connection else None)
        linked = frozenset(connection.linked) if connection else frozenset()
        made = (merchant_of(entry, connection is not None, linked, self._settings) for entry in entries)
        return [m for m in made if category in (None, m.category)]

    async def merchant(self, merchant_id: str) -> Merchant | None:
        if index_id_of(merchant_id) is None:
            return None
        return next((m for m in await self.merchants() if m.id == merchant_id), None)

    async def _entry(self, merchant: Merchant) -> Entry:
        found = await self._catalog.entry(index_id_of(merchant.id) or "")
        if found is None:
            raise DomainError("MERCHANT_NOT_AVAILABLE", f"{merchant.name} is no longer in Index's directory.")
        return found

    async def _asking[T](self, work: Callable[[Preview], Awaitable[T]]) -> T:
        """`work` with a preview session on the owner's Index account; Index's trouble is a refusal."""
        if account_of_call() is None:
            raise not_connected()

        async def with_token(token: str) -> T:
            return await work(Preview(self._sessions(token)))

        try:
            return await self._tokens.run(self._ledger.owner(), with_token)
        except IndexProblem as problem:
            raise refusal_of(problem) from problem
        except NotLinked:
            await self._store.unlink(self._ledger.owner(), kind_food.MERCHANT)
            raise

    async def offers(self, merchant: Merchant, query: str | None = None) -> list[Offer]:
        if merchant.requires_link:
            raise DomainError(
                "LINK_REQUIRED",
                f"{merchant.name} needs the person to connect their account first. Call connect_account for "
                f"it: "
                "its card is where they connect.",
            )
        entry = await self._entry(merchant)
        match entry.kind:
            case "airtime":
                return kind_airtime.offers_of(merchant, entry)
            case "electricity":
                return kind_electricity.offers_of(merchant, entry)
            case _:
                return await self._asking(lambda preview: kind_food.offers_of(preview, merchant, query))

    async def check(self, merchant: Merchant, fields: Mapping[str, str]) -> AccountLookup:
        entry = await self._entry(merchant)
        if entry.kind != "electricity":
            raise DomainError("CHECK_NOT_NEEDED", f"{merchant.name} does not check accounts. Make the quote.")
        return await self._asking(lambda preview: kind_electricity.check(preview, merchant, entry, fields))

    async def price(self, merchant: Merchant, basket: Basket, check: AccountCheck | None) -> Totals:
        return self._tagged(await self._priced(merchant, basket, check))

    def _tagged(self, totals: Totals) -> Totals:
        """The quote remembers whether it was priced at the real Index, for what its card says about the
        money."""
        assert totals.external is not None
        terms = {**totals.external.terms, "live": self._settings.live}
        return replace(totals, external=replace(totals.external, terms=terms))

    async def _priced(self, merchant: Merchant, basket: Basket, check: AccountCheck | None) -> Totals:
        if merchant.checks_account != (check is not None):
            raise DomainError(
                "ACCOUNT_CHECK_REQUIRED", f"{merchant.name} needs an account check; call check_account first."
            )
        if basket.amount_kobo is not None:
            await self._ledger.assert_quotable(basket.amount_kobo)
        entry = await self._entry(merchant)
        match entry.kind:
            case "airtime":
                return await self._asking(lambda p: kind_airtime.price(p, merchant, entry, basket))
            case "electricity":
                assert check is not None
                return await self._asking(lambda p: kind_electricity.price(p, merchant, entry, basket, check))
            case _:
                return await self._asking(lambda p: kind_food.price(p, merchant, basket))

    def request_id(self, quote: Quote, now: int) -> str:
        return f"mrq-{quote.id}"

    async def fulfil(self, quote: Quote) -> Outcome:
        return await self._fulfilment.fulfil(quote)

    async def status(self, quote: Quote) -> Outcome:
        return await self._fulfilment.status(quote)
