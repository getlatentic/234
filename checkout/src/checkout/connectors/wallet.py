# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `wallet` connector: a signed-in person's 234 wallet (docs/wallet.md).

The model has one tool, `wallet_balance`, which reads: the balance as a line, and the wallet card. The card
calls the rest: `wallet_view` to show the wallet as it stands, and `start_topup` for a Bachs checkout to add
money on. No tool here spends; paying from the wallet is a choice on an approval card. Every call acts for the
account the host named (wallet/access.py), and the wallet is opened the first time that account asks."""

import secrets
from typing import Annotated, Any

from pydantic import Field

from ..audit import Audit
from ..db import Db
from ..mcp.registry import APP_ONLY, MODEL_ONLY, Connector, Tool, ToolResult, UiResource
from ..money import KOBO_PER_NAIRA, format_naira
from ..wallet.access import wallet_owner
from ..wallet.topups import TopUp, TopUps
from ..wallet.view import WalletView
from .kit import CardReader, Strict, plain_result

NAME = "wallet"
CARD_URI = f"ui://{NAME}/card.html"
CARD_ID_HEX = 32
MIN_TOPUP_NAIRA = 100
MAX_TOPUP_NAIRA = 1_000_000

READ_HINTS = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
TOPUP_HINTS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}

CardId = Annotated[
    str, Field(pattern=rf"^[0-9a-f]{{{CARD_ID_HEX}}}$", description="The card_id of the wallet card asking.")
]


class Nothing(Strict):
    pass


class ViewWallet(Strict):
    card_id: CardId


class StartTopUp(Strict):
    card_id: CardId
    amount_naira: Annotated[int, Field(ge=MIN_TOPUP_NAIRA, le=MAX_TOPUP_NAIRA, description="Whole naira.")]


def new_card_id() -> str:
    return secrets.token_hex(CARD_ID_HEX // 2)


def topup_view(topup: TopUp) -> dict[str, Any]:
    return {
        "id": topup.id,
        "amountKobo": topup.amount_kobo,
        "amount": format_naira(topup.amount_kobo),
        "checkoutUrl": topup.checkout_url,
    }


class WalletTools:
    def __init__(self, topups: TopUps, db: Db, audit: Audit) -> None:
        self._topups = topups
        self._view = WalletView(topups.journal, db)
        self._audit = audit

    async def _opened(self) -> str:
        owner = wallet_owner()
        await self._topups.journal.open(owner)
        return owner

    async def _card(self, owner: str, card_id: str, **more: Any) -> dict[str, Any]:
        return {"card_id": card_id, "wallet": await self._view.of(owner), **more}

    async def balance(self, _: Nothing) -> ToolResult:
        data = await self._card(await self._opened(), new_card_id())
        return plain_result(f"The wallet holds {data['wallet']['balance']}.", data)

    async def view(self, args: ViewWallet) -> ToolResult:
        data = await self._card(await self._opened(), args.card_id)
        return plain_result(f"The wallet holds {data['wallet']['balance']}.", data)

    async def start_topup(self, args: StartTopUp) -> ToolResult:
        owner = await self._opened()
        topup = await self._topups.start(owner, args.amount_naira * KOBO_PER_NAIRA)
        self._audit.log("wallet.topup_started", topup=topup.id, amount_kobo=topup.amount_kobo)
        data = await self._card(owner, args.card_id, topup=topup_view(topup))
        return plain_result(f"Adding {format_naira(topup.amount_kobo)}: pay on the checkout.", data)


def _tools(tools: WalletTools) -> tuple[Tool, ...]:
    def card(name: str, what: str, arguments: type[Strict], run: Any, hints: dict[str, Any]) -> Tool:
        description = f"Called by the wallet card {what}. Not for the model."
        return Tool(name, name, description, arguments, run, CARD_URI, APP_ONLY, hints)

    return (
        Tool(
            "wallet_balance",
            "Wallet balance",
            "Shows the person's 234 wallet: its balance, the latest entries, and a card where they add "
            "money. Use it when they ask about their wallet or balance or want to add money. You cannot "
            "add, move or spend wallet money: they pay from the wallet on an approval card.",
            Nothing,
            tools.balance,
            CARD_URI,
            MODEL_ONLY,
            READ_HINTS,
        ),
        card("wallet_view", "to show the wallet as it stands", ViewWallet, tools.view, READ_HINTS),
        card("start_topup", "when the person presses Add money", StartTopUp, tools.start_topup, TOPUP_HINTS),
    )


def build_connector(topups: TopUps, db: Db, audit: Audit, card_html: CardReader) -> Connector:
    card = UiResource(
        CARD_URI, "Wallet card", "Shows the wallet's balance and latest entries, and adds money.", card_html
    )
    return Connector(
        name=NAME,
        title="Wallet",
        instructions=(
            "A signed-in person's 234 wallet. wallet_balance shows the balance and the wallet card, where "
            "they add money. You never move wallet money: paying from it is the person's choice on an "
            "approval card."
        ),
        tools=_tools(WalletTools(topups, db, audit)),
        resources=(card,),
        audit=audit,
    )
