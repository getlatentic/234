# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a quote for an Index merchant remembers so that, once the person approves it, the order can be placed:
the Index tool and the arguments it was previewed with. Everything before the approval goes through a
`Preview`, which refuses any call that could spend (`confirmed`); the placing after it is `fulfil.py`'s alone.
Purchases are paid from the person's Zap balance, so a quote is made only when Zap is linked and covers it."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...errors import DomainError
from ...money import Kobo
from ..model import ExternalFunding
from .reading import flat, kobo_in, words
from .wire import IndexMisread, IndexSession, ToolReply

ZAP = "your Zap balance at Paystack Index"
SPENDS = "confirmed"


@dataclass(frozen=True)
class Purchase:
    kind: str
    tool: str
    arguments: Mapping[str, Any]
    two_phase: bool
    """The tool previews first and charges only when called again with `confirmed`."""

    def terms(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "twoPhase": self.two_phase,
        }

    @classmethod
    def from_terms(cls, terms: Mapping[str, Any]) -> Purchase:
        return cls(terms["kind"], terms["tool"], terms["arguments"], terms["twoPhase"])

    def confirmed_arguments(self) -> dict[str, Any]:
        return {**self.arguments, SPENDS: True} if self.two_phase else dict(self.arguments)


class Preview:
    """A session that can only look. A call that carries `confirmed` is a bug in 234, not a request."""

    def __init__(self, session: IndexSession) -> None:
        self._session = session

    async def call(self, name: str, arguments: Mapping[str, Any]) -> ToolReply:
        if SPENDS in arguments:
            raise RuntimeError(f"a preview of {name} carried {SPENDS}")
        return await self._session.call(name, arguments)


class NotLinked(DomainError):
    """Index says the merchant is not linked to the person's account. Its own words tell an assistant to ask
    for a phone number; 234's tell the model to open the connect card, where the person does it."""

    def __init__(self, merchant: str) -> None:
        super().__init__(
            "LINK_REQUIRED",
            f"{merchant} is not linked to the person's Paystack Index account. Call connect_account for it: "
            "its card is where they link it, and nothing about it goes through the chat. Nothing was "
            "charged.",
        )


def says_unlinked(text: str) -> bool:
    lowered = text.lower()
    return "not linked" in lowered or "connect_merchant" in lowered


def refused(reply: ToolReply, code: str, what: str, merchant: str = "The merchant") -> DomainError:
    """Index's refusal as ours: its words are third-party text, short and on one line."""
    if says_unlinked(reply.text):
        return NotLinked(merchant)
    detail = words(reply.text, 160)
    return DomainError(
        code, f"Paystack Index would not {what}{': ' + detail if detail else ''}. Nothing was charged."
    )


async def zap_funding(preview: Preview, total: Kobo, purchase: Purchase) -> ExternalFunding:
    """The funding of an order Zap pays, or the refusal: Zap not linked, not readable, or too short."""
    reply = await preview.call("get_balance", {})
    if reply.is_error:
        raise refused(reply, "INDEX_REFUSED", "show the balance")
    data = flat(reply.data)
    if data.get("zap_linked") is not True:
        raise DomainError(
            "ZAP_NOT_LINKED",
            "The person has no Zap account linked at Paystack Index, and Index pays from Zap. They can link "
            "one in their Index dashboard. Nothing was quoted.",
        )
    zap, credits = kobo_in(data, "zap_balance"), kobo_in(data, "balance") or 0
    if zap is None:
        raise IndexMisread("Index did not say the Zap balance.")
    if zap + credits < total:
        raise DomainError(
            "ZAP_SHORT",
            "Their Zap balance does not cover this order. Nothing was quoted; they can add to Zap.",
        )
    return ExternalFunding(ZAP, zap - max(total - credits, 0), purchase.terms())
