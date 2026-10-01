# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Django host's guards, run against the host's own tests: who may call which tool, how a card opens
another, what a card page may load, and who makes the idempotency key of a quote call. The tests of the
host run in the host's environment."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

HUB = ["tests/test_hub.py"]
CARDS = ["tests/test_card_calls.py", "tests/test_chat_core.py"]
OWNER = ["tests/test_owner.py"]
KEYS = ["tests/test_hub_keys.py", "tests/test_idempotency.py", "tests/test_runner_keys.py"]


MUTATIONS: list[Mutation] = [
    host(
        "the model cannot call an app-only tool",
        "turns/hub.py",
        'if "model" not in visibility_of(tool):\n            return refused(',
        "if False:\n            return refused(",
        HUB,
    ),
    host(
        "the model is offered model-visible tools only",
        "turns/hub.py",
        'if "model" not in visibility_of(tool):\n                    continue',
        "if False:\n                    continue",
        HUB,
    ),
    host(
        "a card cannot call a tool that is only for the model",
        "turns/hub.py",
        'if "app" not in visibility_of(tool):',
        "if False:",
        HUB,
    ),
    host(
        "a card may call only the tools its own view lists",
        "turns/card_calls.py",
        "if listed is None or card_uri_of(listed) != view:",
        "if listed is None:",
        CARDS,
    ),
    host(
        "a card must be one of this chat's, made by the server it calls",
        "turns/card_calls.py",
        'if card is None or card["server"] != server:',
        "if card is None:",
        CARDS,
    ),
    host(
        "a card's call names one card, by its quote or its own id",
        "turns/card_calls.py",
        "if len(refs) != 1:",
        "if len(refs) < 1:",
        CARDS,
    ),
    host(
        "the card that asked for another card is told where things stand, never given the quote or the token",
        "turns/card_calls.py",
        "        return told\n",
        "        return result\n",
        CARDS,
    ),
    host(
        "the model's note about an order carries no approval token",
        "turns/card_calls.py",
        "await self._note(_note_for(server, quote))",
        'await self._note(_note_for(server, quote) + " " + str(result["_meta"]["approvalToken"]))',
        CARDS,
    ),
    host(
        "a card asked for by a result is opened once, however often and from however many tabs",
        "turns/card_calls.py",
        'if await self._card(quote["id"]) is None:',
        "if True:",
        CARDS,
    ),
    host(
        "a result may only ask for a card of its own connector, for a quote",
        "turns/card_calls.py",
        'or not uri.startswith(f"ui://{server}/")',
        "",
        CARDS,
    ),
    host(
        "a card that is not a quote card is named by the id its data gives",
        "turns/card_calls.py",
        'ref = (data.get("quote") or {}).get("id") or data.get("card_id")',
        'ref = (data.get("quote") or {}).get("id")',
        CARDS,
    ),
    host(
        "the page reads the card of every connector the model is offered",
        "config/settings.py",
        'runtime.get_list("CONNECTORS", ",".join(TurnSettings.connectors))',
        'runtime.get_list("CONNECTORS", "paystack-pay")',
        ["tests/test_connectors_default.py"],
    ),
    host(
        "the host names whose money a tool call touches, in a header of its own",
        "turns/hub.py",
        "if owner is not None:\n            headers[OWNER_HEADER] = owner",
        "if False:\n            headers[OWNER_HEADER] = owner",
        OWNER,
    ),
    host(
        "nothing the model or a card sends becomes the owner of a call",
        "turns/hub.py",
        '"tools/call", params, _owner_key(owner), notes=server == MEMORY_SERVER',
        '"tools/call", params, arguments.get("owner", owner), notes=server == MEMORY_SERVER',
        OWNER,
    ),
    host(
        "a key that is not an owner is refused before a call is sent",
        "turns/hub.py",
        "if not _OWNER.fullmatch(owner):",
        "if False:",
        OWNER,
    ),
    host(
        "a visitor's own id is their key",
        "turns/ledger_owner.py",
        "return found[1] if found else hashlib",
        "return hashlib",
        OWNER,
    ),
    host(
        "the model's calls are made for the chat's owner",
        "turns/runner.py",
        "owner = ledger_owner(self._owner)\n",
        'owner = "0" * 32\n',
        OWNER,
    ),
    host(
        "a card's calls are made for the chat's owner",
        "turns/card_calls.py",
        "result = await self._hub.call_app_tool(server, name, arguments, await self._owner())",
        'result = await self._hub.call_app_tool(server, name, arguments, "0" * 32)',
        OWNER,
    ),
    host(
        "a payment webhook's refresh is made for the chat's owner",
        "turns/card_calls.py",
        'card["server"], "verify_quote", {"quote_id": quote_id}, await self._owner()',
        'card["server"], "verify_quote", {"quote_id": quote_id}, "0" * 32',
        OWNER,
    ),
    host(
        "the host overwrites the model's idempotency key",
        "turns/hub.py",
        "arguments = {**arguments, KEY_FIELD: key}",
        "arguments = {KEY_FIELD: key, **arguments}",
        KEYS,
    ),
    host(
        "a tool that takes no idempotency key is sent none",
        "turns/hub.py",
        "        if takes_key(tool):\n            arguments =",
        "        if True:\n            arguments =",
        KEYS,
    ),
    host(
        "the model-facing schema omits the idempotency key",
        "turns/hub.py",
        'schema["properties"] = {k: v for k, v in properties.items() if k not in hidden}',
        'schema["properties"] = dict(properties)',
        KEYS,
    ),
    host(
        "the model-facing schema does not require the idempotency key",
        "turns/hub.py",
        'schema["required"] = [name for name in dict.fromkeys(required) if name not in hidden]',
        'schema["required"] = list(dict.fromkeys(required))',
        KEYS,
    ),
    host(
        "the derived key differs per tool call",
        "turns/idempotency.py",
        "[_DOMAIN, owner, chat_id, call_id]",
        "[_DOMAIN, owner, chat_id]",
        KEYS,
    ),
    host(
        "the derived key differs per chat",
        "turns/idempotency.py",
        "[_DOMAIN, owner, chat_id, call_id]",
        "[_DOMAIN, owner, call_id]",
        KEYS,
    ),
    host(
        "the derived key differs per owner",
        "turns/idempotency.py",
        "[_DOMAIN, owner, chat_id, call_id]",
        "[_DOMAIN, chat_id, call_id]",
        KEYS,
    ),
    host(
        "the runner derives the key from the chat and the call's own id",
        "turns/runner.py",
        'key = derive_key(owner, self._log.chat_id, call["id"])',
        'key = derive_key(owner, self._log.chat_id, call["name"])',
        KEYS,
    ),
    host(
        "a call id is never shared by two calls of a chat",
        "turns/calls.py",
        "if not call_id or call_id in seen:",
        "if not call_id:",
        KEYS,
    ),
    host(
        "a quote request repeated inside one reply is made once",
        "turns/runner.py",
        "elif twin := await self._twin_in_reply(call, reply_calls):",
        "elif False:",
        KEYS,
    ),
    host(
        "only a tool that takes a key has its repeat held back",
        "turns/runner.py",
        'return twin if twin and await self._hub.keyed(call["name"]) else None',
        "return twin",
        KEYS,
    ),
]
