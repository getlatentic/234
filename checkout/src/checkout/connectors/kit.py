# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the four connectors share: the tools only a card calls, the status tool, the card resource and
the mode banner. Each connector adds its own model tools and its instructions."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from ..flows.base import CardFlow
from ..flows.context import Context, QuoteIssued
from ..mcp.registry import (
    APP_ONLY,
    MODEL_ONLY,
    Connector,
    JsonResource,
    Tool,
    ToolResult,
    UiResource,
)
from ..modes import describe_mode
from ..paystack.inline import INLINE_CHECKOUT_CSP
from ..present import summarise

MODE_URI = "paystack-demo://mode"

CardReader = Callable[[], Awaitable[str]]
SubmitOtpRun = Callable[[str, str], Awaitable[dict[str, Any]]]

SAFETY = (
    "You never supply an amount or a recipient to a payment. Make a quote; the server holds it, "
    "and the card shows it to the person.",
    "You cannot approve anything. The person approves on the card. Never ask for or accept card "
    "numbers, PINs, CVVs or passwords; payment happens on Paystack's own checkout page.",
    "Pass the amount as the person said it in amount_as_user_said. If it does not match "
    "amount_kobo, or is unclear, the quote is refused; ask the person to say the amount again.",
    "Use a fresh idempotency_key for each new request and repeat the same key when retrying the "
    "same request.",
    "After the person has used the card, call get_quote_status and report only what it says.",
)

QUOTE_HINTS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
CARD_HINTS = {**QUOTE_HINTS, "destructiveHint": True}

QuoteId = Annotated[
    str,
    Field(min_length=3, max_length=64, description="The quote id, for example qt-0123456789abcdef0123."),
]
IdempotencyKey = Annotated[
    str,
    Field(
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="A unique key for this request. Repeat it to retry the same request safely.",
    ),
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuoteRef(Strict):
    quote_id: QuoteId


class ApproveQuote(Strict):
    quote_id: QuoteId
    approval_token: Annotated[str, Field(min_length=1, max_length=200)]
    displayed_amount_kobo: int
    readback_confirmed: bool | None = None


class VerifyQuote(Strict):
    quote_id: QuoteId
    checkout_closed: bool | None = None


class DeclineQuote(Strict):
    quote_id: QuoteId
    approval_token: Annotated[str, Field(min_length=1, max_length=200)]


class SubmitOtp(Strict):
    quote_id: QuoteId
    otp: Annotated[str, Field(min_length=4, max_length=10)]


def card_result(view: dict[str, Any], text: str, meta: dict[str, Any] | None = None) -> ToolResult:
    result: ToolResult = {
        "content": [{"type": "text", "text": text}],
        "structuredContent": {"quote": view},
    }
    if meta:
        result["_meta"] = meta
    return result


def plain_result(text: str, data: dict[str, Any]) -> ToolResult:
    return {"content": [{"type": "text", "text": text}], "structuredContent": data}


def instructions_for(purpose: str, mode_label: str, extra: tuple[str, ...] = ()) -> str:
    return "\n".join([f"{purpose} ({mode_label}).", *extra, *SAFETY])


@dataclass(frozen=True)
class CardConnector:
    """One connector's identity and the flow behind its card."""

    name: str
    title: str
    ctx: Context
    flow: CardFlow
    card_html: CardReader
    alt_cards: dict[str, CardReader] = field(default_factory=dict)

    @property
    def card_uri(self) -> str:
        return f"ui://{self.name}/card.html"

    def describe_issued(self, issued: QuoteIssued) -> str:
        """What the model is told after a quote is made: the facts, what the person will do, and what
        it must not do."""
        read_back = issued.quote["details"].get("readBack")
        ask = f' Read this back to the person before they approve: "{read_back}".' if read_back else ""
        return (
            f"{summarise(issued.quote)}{ask} The approval card is now shown to the person. You cannot "
            f"approve it. Wait for them, then call get_quote_status on the {self.name} connector to "
            "report what happened."
        )

    def issued_result(self, issued: QuoteIssued, opens_card: bool = False) -> ToolResult:
        """A quote just made, as a tool result. The token is in `_meta` only; `opens_card` says the caller
        is another card, and the host is to mount the approval card for this quote."""
        meta: dict[str, Any] = {"approvalToken": issued.approval_token}
        if opens_card:
            meta["ui"] = {"resourceUri": self.card_uri}
        return card_result(issued.quote, self.describe_issued(issued), meta)

    def quote_tool[A: BaseModel](
        self,
        name: str,
        title: str,
        description: str,
        arguments: type[A],
        run: Callable[[A], Awaitable[QuoteIssued]],
    ) -> Tool:
        """A tool the model calls to make a quote; the approval card is shown for it."""

        async def handler(args: A) -> ToolResult:
            return self.issued_result(await run(args))

        return Tool(name, title, description, arguments, handler, self.card_uri, MODEL_ONLY, QUOTE_HINTS)

    def card_quote_tool[A: BaseModel](
        self,
        name: str,
        description: str,
        arguments: type[A],
        run: Callable[[A], Awaitable[QuoteIssued]],
        view_uri: str,
    ) -> Tool:
        """A tool only a card calls to make a quote: the result opens the approval card next to the
        card that asked, and the model never calls it."""

        async def handler(args: A) -> ToolResult:
            return self.issued_result(await run(args), opens_card=True)

        return Tool(name, name, description, arguments, handler, view_uri, APP_ONLY, QUOTE_HINTS)

    def plain_tool[A: BaseModel](
        self,
        name: str,
        title: str,
        description: str,
        arguments: type[A],
        run: Callable[[A], Awaitable[ToolResult]],
    ) -> Tool:
        """A tool the model calls that returns text and data but shows no card."""
        return Tool(name, title, description, arguments, run, annotations=QUOTE_HINTS)

    def view_tool[A: BaseModel](
        self,
        name: str,
        title: str,
        description: str,
        arguments: type[A],
        run: Callable[[A], Awaitable[ToolResult]],
        view_uri: str,
    ) -> Tool:
        """A tool the model calls whose result a view shows the person, instead of the model repeating it."""
        return Tool(name, title, description, arguments, run, view_uri, MODEL_ONLY, QUOTE_HINTS)

    def _status_tool(self) -> Tool:
        async def status(args: QuoteRef) -> ToolResult:
            view = await self.flow.status(args.quote_id)
            # The checkout link is for the person's browser; the model is told the state, not handed the link.
            return card_result({**view, "checkoutUrl": None}, summarise(view))

        return Tool(
            "get_quote_status",
            "Get quote status",
            "Checks a quote and returns its state from the server's own record: waiting for "
            "approval, in progress, succeeded, failed, or expired. Use it to report the outcome "
            "after the person has used the card. Never say a payment happened until this says "
            "succeeded.",
            QuoteRef,
            status,
            annotations=QUOTE_HINTS,
        )

    def _card_tools(self, submit: SubmitOtpRun | None) -> tuple[Tool, ...]:
        flow = self.flow

        async def approve(args: ApproveQuote) -> ToolResult:
            view = await flow.approve(
                args.quote_id, args.approval_token, args.displayed_amount_kobo, args.readback_confirmed
            )
            return card_result(view, summarise(view), await flow.card_meta(args.quote_id))

        async def verify(args: VerifyQuote) -> ToolResult:
            view = await flow.verify(args.quote_id, bool(args.checkout_closed))
            return card_result(view, summarise(view), await flow.card_meta(args.quote_id))

        async def decline(args: DeclineQuote) -> ToolResult:
            view = await flow.decline(args.quote_id, args.approval_token)
            return card_result(view, summarise(view))

        def card_tool(
            name: str, what: str, arguments: type[BaseModel], run: Callable[[Any], Awaitable[ToolResult]]
        ) -> Tool:
            description = f"Called by the approval card {what}. Not for the model."
            return Tool(name, name, description, arguments, run, self.card_uri, APP_ONLY, CARD_HINTS)

        tools = [
            card_tool("approve_quote", "when the person presses Approve", ApproveQuote, approve),
            card_tool("verify_quote", "to check on a quote", VerifyQuote, verify),
            card_tool("decline_quote", "when the person presses Decline", DeclineQuote, decline),
        ]
        if submit is not None:

            async def submit_otp(args: SubmitOtp) -> ToolResult:
                view = await submit(args.quote_id, args.otp)
                return card_result(view, summarise(view))

            tools.append(
                card_tool(
                    "submit_otp",
                    "with the one-time code the person typed",
                    SubmitOtp,
                    submit_otp,
                )
            )
        return tuple(tools)

    def _card_meta_ui(self) -> dict[str, Any]:
        """The approval card asks for Paystack's popup only where it can use it: in Paystack test mode."""
        csp: dict[str, list[str]] = {
            name: [*origins]
            for name, origins in (INLINE_CHECKOUT_CSP if self.ctx.inline_checkout else {}).items()
        }
        for name, origins in self.ctx.card_csp_extra.items():
            csp[name] = [*csp.get(name, []), *origins]
        return {"prefersBorder": False, **({"csp": csp} if csp else {})}

    def _resources(self, views: tuple[UiResource, ...]) -> tuple[UiResource | JsonResource, ...]:
        mode = describe_mode(self.ctx.modes)

        async def banner() -> dict[str, Any]:
            return {
                "connector": self.name,
                "title": self.title,
                "label": mode.label,
                "simulated": mode.simulated,
                "modes": self.ctx.modes.as_dict(),
            }

        return (
            UiResource(
                self.card_uri,
                f"{self.title} approval card",
                "Shows a quote as the server holds it, with Approve and Decline, then the receipt.",
                self.card_html,
                self._card_meta_ui(),
            ),
            *views,
            *(
                UiResource(
                    f"ui://{self.name}/card-{name}.html",
                    f"Alternative approval card: {name}",
                    "A second card, for comparing implementations against the same server.",
                    read,
                )
                for name, read in self.alt_cards.items()
            ),
            JsonResource(
                MODE_URI,
                "Connector mode",
                "The connector's name and whether it moves any money, for a host's banner.",
                banner,
            ),
        )

    def build(
        self,
        purpose: str,
        model_tools: tuple[Tool, ...],
        extra: tuple[str, ...] = (),
        submit_otp: SubmitOtpRun | None = None,
        views: tuple[UiResource, ...] = (),
        app_tools: tuple[Tool, ...] = (),
    ) -> Connector:
        mode = describe_mode(self.ctx.modes)
        return Connector(
            name=self.name,
            title=self.title,
            instructions=instructions_for(purpose, mode.label, extra),
            tools=(*model_tools, self._status_tool(), *self._card_tools(submit_otp), *app_tools),
            resources=self._resources(views),
            audit=self.ctx.audit,
        )
