# SPDX-License-Identifier: AGPL-3.0-or-later
"""Doubles for a card's calls: a hub that lists the tools each view owns, and results shaped like a menu
card's search and its order."""

from turns.hub import ToolOutcome

MENU = "ui://s/menu.html"
APPROVAL = "ui://s/card.html"
SEARCH = "s__search"
MAKE = "s__make"
CARD_ID = "0123456789abcdef0123456789abcdef"


def listed(name: str, view: str | None, visibility: str) -> dict:
    meta = {"ui": {"visibility": [visibility], **({"resourceUri": view} if view else {})}}
    return {"name": name, "inputSchema": {}, "_meta": meta}


LISTING = {
    "s": [
        listed("search", MENU, "model"),
        listed("make", APPROVAL, "model"),
        listed("order_from_menu", MENU, "app"),
        listed("approve_quote", APPROVAL, "app"),
        listed("verify_quote", APPROVAL, "app"),
    ]
}


def menu_result(card_id: str = CARD_ID) -> dict:
    return {
        "content": [{"type": "text", "text": "Mama Put: 11 items match. The card shows them."}],
        "structuredContent": {"card_id": card_id, "merchant": "Mama Put", "items": [{"item_id": "zobo"}]},
    }


def ordered(quote_id: str = "qt-9", token: str = "tok-menu-order") -> dict:
    return {
        "content": [{"type": "text", "text": f"Quote {quote_id}: ₦2,000."}],
        "structuredContent": {
            "quote": {
                "id": quote_id,
                "phase": "awaiting_approval",
                "amount": {"kobo": 200_000, "display": "₦2,000"},
            }
        },
        "_meta": {"approvalToken": token, "ui": {"resourceUri": APPROVAL}},
    }


class CardHub:
    """The connectors as a host sees them: model tools scripted by name, app tools by their own name."""

    def __init__(self, model=None, app=None, views=None):
        self.model = model or {}
        self.app = app or {}
        self.views = views or {SEARCH: MENU, MAKE: APPROVAL}
        self.app_calls: list[tuple[str, str, dict]] = []
        self.owners: list[str] = []
        self.accounts: list[bool] = []

    async def model_tools(self):
        return [{"type": "function", "function": {"name": name, "parameters": {}}} for name in self.model]

    async def tools(self, server: str):
        return LISTING[server]

    async def call_model_tool(
        self, qualified: str, arguments: dict, owner: str, key: str, account: bool = False
    ):
        self.owners.append(owner)
        server, _, tool = qualified.partition("__")
        return ToolOutcome(server, tool, self.model[qualified], self.views.get(qualified))

    async def call_app_tool(self, server: str, name: str, arguments: dict, owner: str, account: bool = False):
        self.app_calls.append((server, name, arguments))
        self.owners.append(owner)
        self.accounts.append(account)
        answer = self.app[name]
        if isinstance(answer, Exception):
            raise answer
        return answer
