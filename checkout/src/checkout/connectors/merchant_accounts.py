# SPDX-License-Identifier: AGPL-3.0-or-later
"""Connecting a person's own account for a merchant (docs/commerce.md, "Connecting"): the model's one tool,
`connect_account`, opens a card, and everything on the card is done by the person. The tools the card
calls carry what only the person has (a phone number, a texted code) from the card to the server, and the
host's sign-in redirect lands in `complete_connection`. None of them is offered to the model, and none
returns a token. A guest of a shared chat cannot press the card's buttons (the host refuses them), and
every tool here acts for the signed-in account of the call and for no other."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from pydantic import Field

from ..commerce.index.accounts import IndexAccounts
from ..commerce.model import Merchant
from ..errors import DomainError
from ..flows.context import Context
from ..mcp.registry import APP_ONLY, Tool, ToolResult, UiResource
from ..wallet.access import account_of_call
from .kit import CARD_HINTS, READ_HINTS, Strict, plain_result

CARD_URI = "ui://merchants/connect.html"
ACCOUNT_ONLY = "Connecting an account is for signed-in accounts. Sign in to use it."
MODEL_TELLS = (
    "The connect card is now shown to the person. Nothing is connected or disconnected yet: they do it on "
    "the card, signing in at Paystack Index and, for Chowdeck, typing a code texted to their phone, which "
    "you never see. Tell them only that the card is open and what to do on it; never say it is done. You "
    "must not ask for a code, a phone number or a password in the chat. When they say they are done, make "
    "the quote."
)

MerchantId = Annotated[
    str, Field(min_length=2, max_length=40, description="A merchant id from browse_merchants.")
]
CardId = Annotated[str, Field(min_length=23, max_length=23, pattern=r"^cn-[0-9a-f]{20}$")]
Phone = Annotated[str, Field(min_length=7, max_length=24)]


class ConnectAccount(Strict):
    merchant_id: Annotated[
        str | None,
        Field(
            min_length=2,
            max_length=40,
            description="The merchant to connect for, from browse_merchants; leave out for the account.",
        ),
    ] = None


class CardRef(Strict):
    card_id: CardId


class SendLinkCode(Strict):
    card_id: CardId
    phone: Phone


class ConfirmLinkCode(Strict):
    card_id: CardId
    phone: Phone
    code: Annotated[str, Field(min_length=4, max_length=12)]


class Callback(Strict):
    code: Annotated[str, Field(min_length=1, max_length=2000)]
    state: Annotated[str, Field(min_length=1, max_length=200)]


class Declined(Strict):
    state: Annotated[str, Field(min_length=1, max_length=200)]


def _owner(ctx: Context) -> str:
    if account_of_call() is None:
        raise DomainError("ACCOUNT_ONLY", ACCOUNT_ONLY)
    return ctx.ledger.owner()


def _view_result(view: dict, text: str) -> ToolResult:
    return plain_result(text, view)


def card_resource(read: Callable[[], Awaitable[str]]) -> UiResource:
    return UiResource(
        CARD_URI,
        "Connect an account",
        "The card on which the person connects their own account for a merchant, and ends the connection.",
        read,
    )


def _card_tool(
    name: str,
    what: str,
    arguments: type[Strict],
    run: Callable[..., Awaitable[ToolResult]],
    hints: dict[str, bool] = CARD_HINTS,
) -> Tool:
    description = f"Called by the connect card {what}. Not for the model."
    return Tool(name, name, description, arguments, run, CARD_URI, APP_ONLY, hints)


def accounts_tools(
    ctx: Context, accounts: IndexAccounts, merchant_of: Callable[[str], Awaitable[Merchant]]
) -> tuple[Tool, tuple[Tool, ...]]:
    """The model's `connect_account`, and the connect card's tools. `merchant_of` finds a merchant by id."""

    async def connect(args: ConnectAccount) -> ToolResult:
        owner = _owner(ctx)
        merchant = await merchant_of(args.merchant_id) if args.merchant_id else None
        if merchant is not None and merchant.provider != "index":
            raise DomainError("NOTHING_TO_CONNECT", f"{merchant.name} needs no account to be connected.")
        view = await accounts.begin(owner, merchant.id if merchant else None)
        return _view_result(view, MODEL_TELLS)

    async def status(args: CardRef) -> ToolResult:
        return _view_result(await accounts.status(_owner(ctx), args.card_id), "Connection status.")

    async def restart(args: CardRef) -> ToolResult:
        return _view_result(await accounts.restart(_owner(ctx), args.card_id), "A new sign-in link.")

    async def send_code(args: SendLinkCode) -> ToolResult:
        view = await accounts.send_code(_owner(ctx), args.card_id, args.phone)
        return _view_result(view, "A code was asked for.")

    async def confirm(args: ConfirmLinkCode) -> ToolResult:
        view = await accounts.confirm_code(_owner(ctx), args.card_id, args.phone, args.code)
        return _view_result(view, "The code was checked.")

    async def disconnect(args: CardRef) -> ToolResult:
        return _view_result(await accounts.disconnect(_owner(ctx), args.card_id), "Disconnected.")

    async def complete(args: Callback) -> ToolResult:
        view = await accounts.complete(_owner(ctx), args.code, args.state)
        return _view_result(view, "Connected.")

    async def declined(args: Declined) -> ToolResult:
        await accounts.denied(_owner(ctx), args.state)
        return plain_result("The sign-in was declined.", {})

    model = Tool(
        "connect_account",
        "Connect an account",
        "Opens a card on which the person connects their own Paystack Index account, which pays for "
        "Chowdeck food, airtime and electricity, links Chowdeck, or disconnects it. They do it on the card; "
        "you cannot, "
        "and you never see a code. Call it now, in the same reply, when they ask to use, connect or "
        "disconnect Index or a merchant needs them to connect (browse_merchants says so), whatever else "
        "is missing; never ask first. Leave merchant_id out for the account itself.",
        ConnectAccount,
        connect,
        CARD_URI,
        ("model",),
        {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    )
    return model, (
        _card_tool("connection_status", "to see how the connection stands", CardRef, status, READ_HINTS),
        _card_tool("restart_connection", "to get a fresh sign-in link", CardRef, restart),
        _card_tool("send_link_code", "with the phone number the person typed", SendLinkCode, send_code),
        _card_tool("confirm_link_code", "with the code the person typed", ConfirmLinkCode, confirm),
        _card_tool("disconnect_account", "when the person presses Disconnect", CardRef, disconnect),
        _card_tool(
            "complete_connection", "by the chat host when Index sends the person back", Callback, complete
        ),
        _card_tool(
            "connection_declined", "by the chat host when the person said no at Index", Declined, declined
        ),
    )
