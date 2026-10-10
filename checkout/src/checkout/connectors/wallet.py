# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `wallet` connector: a signed-in person's 234 wallet (docs/wallet.md).

The model has one tool, `wallet_balance`, which reads: the balance as a line, and the wallet card. The card
calls the rest: `wallet_view` to show the wallet as it stands, `start_topup` for a Bachs checkout to add
money on, and `start_withdrawal` and `withdraw` to send money to a bank account (wallet_withdraw.py). The
model can move no money: paying from the wallet is a choice on an approval card, and withdrawing is the
card's. Every call acts for the
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
from ..wallet.withdrawal_record import withdrawal_view
from ..wallet.withdrawals import Withdrawals
from .kit import CardReader, Strict, plain_result
from .wallet_withdraw import (
    MIN_WITHDRAWAL_NAIRA,
    OUT_HINTS,
    WithdrawalId,
    outcome_text,
    with_token,
)

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
    withdrawal_id: WithdrawalId | None = None


class StartTopUp(Strict):
    card_id: CardId
    amount_naira: Annotated[int, Field(ge=MIN_TOPUP_NAIRA, le=MAX_TOPUP_NAIRA, description="Whole naira.")]


class StartWithdrawal(Strict):
    card_id: CardId
    amount_naira: Annotated[int, Field(ge=MIN_WITHDRAWAL_NAIRA, description="Whole naira.")]
    bank: Annotated[str, Field(min_length=1, max_length=60, description="The bank, as the person typed it.")]
    account_number: Annotated[str, Field(min_length=10, max_length=14, description="10 digits.")]


class Withdraw(Strict):
    card_id: CardId
    withdrawal_id: WithdrawalId
    withdrawal_token: Annotated[str, Field(min_length=1, max_length=200)]
    displayed_amount_kobo: Annotated[int, Field(gt=0)]
    confirmed_name: Annotated[str, Field(min_length=1, max_length=200)]


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
    def __init__(self, topups: TopUps, withdrawals: Withdrawals, db: Db, audit: Audit) -> None:
        self._topups = topups
        self._withdrawals = withdrawals
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
        owner = await self._opened()
        found = await self._withdrawals.get(owner, args.withdrawal_id) if args.withdrawal_id else None
        more = {"withdrawal": withdrawal_view(found)} if found else {}
        data = await self._card(owner, args.card_id, **more)
        return plain_result(f"The wallet holds {data['wallet']['balance']}.", data)

    async def start_topup(self, args: StartTopUp) -> ToolResult:
        owner = await self._opened()
        topup = await self._topups.start(owner, args.amount_naira * KOBO_PER_NAIRA)
        self._audit.log("wallet.topup_started", topup=topup.id, amount_kobo=topup.amount_kobo)
        data = await self._card(owner, args.card_id, topup=topup_view(topup))
        return plain_result(f"Adding {format_naira(topup.amount_kobo)}: pay on the checkout.", data)

    async def start_withdrawal(self, args: StartWithdrawal) -> ToolResult:
        owner = await self._opened()
        withdrawal = await self._withdrawals.start(
            owner, args.amount_naira * KOBO_PER_NAIRA, args.bank, args.account_number
        )
        data = await self._card(owner, args.card_id, withdrawal=withdrawal_view(withdrawal))
        result = plain_result(f"Confirm the name: {withdrawal.account_name}.", data)
        return with_token(result, self._withdrawals.token(withdrawal.id))

    async def withdraw(self, args: Withdraw) -> ToolResult:
        owner = await self._opened()
        withdrawal = await self._withdrawals.approve(
            owner, args.withdrawal_id, args.withdrawal_token, args.displayed_amount_kobo, args.confirmed_name
        )
        data = await self._card(owner, args.card_id, withdrawal=withdrawal_view(withdrawal))
        return plain_result(outcome_text(withdrawal), data)


def _tools(tools: WalletTools) -> tuple[Tool, ...]:
    def card(name: str, what: str, arguments: type[Strict], run: Any, hints: dict[str, Any]) -> Tool:
        description = f"Called by the wallet card {what}. Not for the model."
        return Tool(name, name, description, arguments, run, CARD_URI, APP_ONLY, hints)

    return (
        Tool(
            "wallet_balance",
            "Wallet balance",
            "Shows the person's 234 wallet: its balance, the latest entries, and a card where they add "
            "money or withdraw it to their bank account. Use it when they ask about their wallet or "
            "balance or want to add or withdraw money. You cannot add, move, withdraw or spend wallet "
            "money: they withdraw on this card and pay from the wallet on an approval card.",
            Nothing,
            tools.balance,
            CARD_URI,
            MODEL_ONLY,
            READ_HINTS,
        ),
        card("wallet_view", "to show the wallet as it stands", ViewWallet, tools.view, READ_HINTS),
        card("start_topup", "when the person presses Add money", StartTopUp, tools.start_topup, TOPUP_HINTS),
        card(
            "start_withdrawal",
            "when the person asks to withdraw, to resolve the account",
            StartWithdrawal,
            tools.start_withdrawal,
            OUT_HINTS,
        ),
        card(
            "withdraw",
            "when the person confirms the name and presses Withdraw",
            Withdraw,
            tools.withdraw,
            OUT_HINTS,
        ),
    )


def build_connector(
    topups: TopUps, withdrawals: Withdrawals, db: Db, audit: Audit, card_html: CardReader
) -> Connector:
    card = UiResource(
        CARD_URI,
        "Wallet card",
        "Shows the wallet's balance and latest entries, adds money and withdraws it.",
        card_html,
    )
    return Connector(
        name=NAME,
        title="Wallet",
        instructions=(
            "A signed-in person's 234 wallet. wallet_balance shows the balance and the wallet card, where "
            "they add money and withdraw it. You never move wallet money: withdrawing is the person's on "
            "the wallet card, and paying from it is their choice on an approval card."
        ),
        tools=_tools(WalletTools(topups, withdrawals, db, audit)),
        resources=(card,),
        audit=audit,
    )
