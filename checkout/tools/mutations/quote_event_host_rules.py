# SPDX-License-Identifier: AGPL-3.0-or-later
"""The host as an MCP events subscriber: an event must carry the host's own signature, an ending delivered
again tells the model once, and a quote card is followed as the chat's own ledger owner. Run against the
host's own tests."""

from tools.mutations.model import Mutation
from tools.mutations.model import host_mutation as host

HOOK = ["tests/test_event_hook.py"]
FOLLOW = ["tests/test_quote_events.py"]

MUTATIONS: list[Mutation] = [
    host(
        "an event must carry the host's own signature",
        "turns/quote_events.py",
        "    return any(hmac.compare_digest(given, expected) "
        'for given in headers.get("webhook-signature", "").split())',
        "    return True",
        HOOK,
    ),
    host(
        "an ending delivered again tells the model once",
        "turns/chat_core.py",
        "            self.chat_id, kinds.EVENT, event_id,\n"
        "        )  # fmt: skip\n        if known is not None:",
        "            self.chat_id, kinds.EVENT, event_id,\n        )  # fmt: skip\n        if False:",
        FOLLOW,
    ),
    host(
        "a quote card is followed as the chat's own ledger owner",
        "turns/runner.py",
        "await quote_events.follow(self._hub, self._settings, outcome, ledger_owner(self._owner))",
        'await quote_events.follow(self._hub, self._settings, outcome, "0" * 32)',
        FOLLOW,
    ),
]
