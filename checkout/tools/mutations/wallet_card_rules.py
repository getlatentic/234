# SPDX-License-Identifier: AGPL-3.0-or-later
"""What keeps the wallet an account's own and its spending the card's choice (docs/wallet.md, step 4): every
wallet call acts for the signed-in account the host names, the wallet is opened for that account alone,
`funding` is taken only by the card's approval and defaults to the checkout, the approval card is offered the
wallet only for an account whose balance covers an open quote, and the host shows and relays the wallet to
accounts alone and never to a guest of a shared chat or an outside client."""

from tools.mutations.model import SRC, Mutation
from tools.mutations.model import host_mutation as host

CONNECTOR = ["tests/test_wallet_connector.py"]
APPROVAL = ["tests/test_wallet_approval_card.py"]
BOTH = [*CONNECTOR, *APPROVAL]
HOST_TESTS = ["tests/test_wallet.py"]
OAUTH = ["tests/test_oauth.py"]


def wallet(name: str, path: str, old: str, new: str, tests: list[str]) -> Mutation:
    return Mutation(f"wallet card: {name}", f"{SRC}/{path}", old, new, tests)


def host_wallet(name: str, path: str, old: str, new: str, tests: list[str] = HOST_TESTS) -> Mutation:
    return host(f"wallet card: {name}", path, old, new, tests)


MUTATIONS: list[Mutation] = [
    wallet(
        "a wallet acts for the account only when it is also whose money the call touches",
        "wallet/access.py",
        "return owner if owner is not None and owner == current_owner() else None",
        "return owner if owner is not None else None",
        CONNECTOR,
    ),
    wallet(
        "a call that names no account reaches no wallet",
        "wallet/access.py",
        "    if owner is None:\n        raise DomainError(ACCOUNT_ONLY",
        "    if False:\n        raise DomainError(ACCOUNT_ONLY",
        APPROVAL,
    ),
    wallet(
        "the connectors refuse a wallet call without the account header",
        "http.py",
        "if given is None and calls_a_tool and connector in ACCOUNT_CONNECTORS:",
        'if given is None and calls_a_tool and connector == "memory":',
        CONNECTOR,
    ),
    wallet(
        "the wallet is opened the first time its account asks",
        "connectors/wallet.py",
        "        await self._topups.journal.open(owner)\n",
        "",
        CONNECTOR,
    ),
    wallet(
        "the card alone views the wallet and adds money: those tools are not the model's",
        "connectors/wallet.py",
        "return Tool(name, name, description, arguments, run, CARD_URI, APP_ONLY, hints)",
        "return Tool(name, name, description, arguments, run, CARD_URI, MODEL_ONLY, hints)",
        CONNECTOR,
    ),
    wallet(
        "paying from the wallet needs the account, checked before the flow runs",
        "connectors/kit.py",
        "                wallet_owner()\n",
        "",
        APPROVAL,
    ),
    wallet(
        "an approval without funding is the checkout, as it always was",
        "connectors/kit.py",
        'funding: Literal["checkout", "wallet"] = "checkout"',
        'funding: Literal["checkout", "wallet"] = "wallet"',
        APPROVAL,
    ),
    wallet(
        "funding is passed by the card alone: the approval tool is not the model's",
        "connectors/kit.py",
        "return Tool(name, name, description, arguments, run, self.card_uri, APP_ONLY, CARD_HINTS)",
        "return Tool(name, name, description, arguments, run, self.card_uri, None, CARD_HINTS)",
        APPROVAL,
    ),
    wallet(
        "the card offers the wallet only when it covers the quote",
        "flows/wallet_leg.py",
        "    if balance < quote.amount_kobo:\n        return None",
        "    if balance < 0:\n        return None",
        APPROVAL,
    ),
    wallet(
        "the card offers the wallet to an account alone",
        "flows/wallet_leg.py",
        "    owner = account_of_call()\n    if owner is None:",
        "    owner = ctx.ledger.owner()\n    if owner is None:",
        APPROVAL,
    ),
    wallet(
        "the card offers the wallet only while the quote is open",
        "flows/wallet_leg.py",
        'if ctx.wallet is None or quote.state != "open":',
        "if ctx.wallet is None:",
        BOTH,
    ),
    host_wallet(
        "only an account's turn is shown the wallet tool",
        "turns/wallet.py",
        'if account or not is_wallet_tool(tool["function"]["name"])',
        "if True",
    ),
    host_wallet(
        "a wallet tool called without an account is refused before it leaves the host",
        "turns/permissions.py",
        "if wallet.is_wallet_tool(qualified) and not self.account:",
        "if False:",
    ),
    host_wallet(
        "a wallet card of a chat that is not an account's reaches nothing",
        "turns/card_calls.py",
        "if server in ACCOUNT_ONLY and not account:",
        "if server == MEMORY_SERVER and not account:",
    ),
    host_wallet(
        "a card's call says whether the chat is an account's",
        "turns/card_calls.py",
        "result = await self._hub.call_app_tool(server, name, arguments, await self._owner(), account)",
        "result = await self._hub.call_app_tool(server, name, arguments, await self._owner())",
    ),
    host_wallet(
        "every connector is told an account's call is an account's",
        "turns/hub.py",
        "notes=account or server == MEMORY_SERVER",
        "notes=server == MEMORY_SERVER",
    ),
    host_wallet(
        "a guest of a shared chat cannot pay from the owner's wallet",
        "chat/views/cards.py",
        "return WALLET_OWNER_ONLY if server == WALLET_SERVER or paid_from_wallet else None",
        "return WALLET_OWNER_ONLY if server == WALLET_SERVER else None",
    ),
    host_wallet(
        "a guest of a shared chat cannot see or add to the owner's wallet",
        "chat/views/cards.py",
        "return WALLET_OWNER_ONLY if server == WALLET_SERVER or paid_from_wallet else None",
        "return WALLET_OWNER_ONLY if paid_from_wallet else None",
    ),
    host_wallet(
        "an outside client is offered no wallet",
        "oauth/resources.py",
        "return tuple(name for name in settings.CONNECTORS if name != WALLET_SERVER)",
        "return tuple(settings.CONNECTORS)",
        OAUTH,
    ),
]
