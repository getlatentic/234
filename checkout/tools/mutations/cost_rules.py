# SPDX-License-Identifier: AGPL-3.0-or-later
"""What bounds the cost of a public deployment (host chat/bot_check.py, turns/budget.py): a first message of a
visitor passes Turnstile, once, for the action and the host it was made for, and a person who is signed in
passes nothing; Cloudflare being down lets the message through; and a day's tokens are capped for everyone and
for each person, read before a round and added after it. Run against the host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

BOT = ["tests/test_bot_check.py"]
BUDGET = ["tests/test_budget.py", "tests/test_runner.py"]

MUTATIONS: list[Mutation] = [
    host(
        "bot check: a visitor's first message is checked",
        "chat/views/send.py",
        "    if refusal := _bot_refusal(request, chat_id):",
        "    if False:",
        BOT,
    ),
    host(
        "bot check: a message to a chat that exists is not checked again",
        "chat/views/send.py",
        "    if Chat.objects.filter(pk=chat_id, owner=request.owner).exists():",
        "    if False:",
        BOT,
    ),
    host(
        "bot check: a signed-in person passes nothing",
        "chat/views/send.py",
        '    if not settings.TURNSTILE_ENABLED or getattr(request, "account", None) is not None:',
        "    if not settings.TURNSTILE_ENABLED:",
        BOT,
    ),
    host(
        "bot check: only the deploy's own ops token passes a first message unchecked",
        "chat/views/send.py",
        "    if bearer_matches(request):\n        return None",
        '    if request.headers.get("Authorization"):\n        return None',
        BOT,
    ),
    host(
        "bot check: a token is for the action and the host it was made for",
        "chat/bot_check.py",
        '    return answer.get("action") == ACTION and answer.get("hostname") in hosts',
        "    return True",
        BOT,
    ),
    host(
        "bot check: a token that is not a short string is refused unasked",
        "chat/bot_check.py",
        "    if not isinstance(token, str) or not token or len(token) > MAX_TOKEN:",
        "    if not isinstance(token, str):",
        BOT,
    ),
    host(
        "bot check: Cloudflare being unreachable lets the message through",
        "chat/bot_check.py",
        "exc_info=True)\n        return UNAVAILABLE",
        "exc_info=True)\n        return REFUSED",
        BOT,
    ),
    host(
        "bot check: Cloudflare answering with a fault lets the message through",
        "chat/bot_check.py",
        "    if status >= 500 or not isinstance(answer, dict):",
        "    if not isinstance(answer, dict):",
        BOT,
    ),
    host(
        "bot check: the page may reach Turnstile only where it is on",
        "chat/security.py",
        "    if not settings.TURNSTILE_ENABLED:\n        return {}",
        "    if False:\n        return {}",
        BOT,
    ),
    host(
        "bot check: only a visitor is offered the widget",
        "chat/views/me.py",
        "settings.TURNSTILE_SITE_KEY if settings.TURNSTILE_ENABLED and account is None else None",
        "settings.TURNSTILE_SITE_KEY if settings.TURNSTILE_ENABLED else None",
        BOT,
    ),
    host(
        "tokens: a person's day is capped",
        "turns/budget.py",
        '    if owner_cap > 0 and await _used(db, f"{TOKENS}{owner}", day) >= owner_cap:',
        "    if False:",
        BUDGET,
    ),
    host(
        "tokens: everyone's day is capped",
        "turns/budget.py",
        '    if global_cap > 0 and await _used(db, f"{TOKENS}{GLOBAL_SCOPE}", day) >= global_cap:',
        "    if False:",
        BUDGET,
    ),
    host(
        "tokens: the cap on tokens is read before a model call",
        "turns/runner.py",
        "        return used_up or await take_model_call(",
        "        return await take_model_call(",
        BUDGET,
    ),
    host(
        "tokens: a round's tokens are counted",
        "turns/runner.py",
        "        await self._count_tokens(finished.usage, sent, tools, streamed.text)",
        "        pass",
        BUDGET,
    ),
]
