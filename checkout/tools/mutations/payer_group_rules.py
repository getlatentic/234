# SPDX-License-Identifier: AGPL-3.0-or-later
"""What one outside agent's people may spend together: the host names the agent's payer group for a chat
it holds as itself, the connectors read it from its header and nowhere else, a quote keeps it, and the
ledger caps the group's approved spend each day at quote time and in the approval statement."""

from tools.mutations.model import SRC, Mutation
from tools.mutations.model import host_mutation as host

GROUPS = ["tests/test_ledger_groups.py"]
LEDGER_FILE = f"{SRC}/ledger.py"

MUTATIONS: list[Mutation] = [
    Mutation(
        "a group's approved spend is capped at quote time",
        LEDGER_FILE,
        "        if group and await self._group_spent(group) + amount > self.limits.group_daily_kobo:",
        "        if False:",
        GROUPS,
    ),
    Mutation(
        "the approval statement caps the group the quote was made in",
        LEDGER_FILE,
        '"FROM quotes AS g WHERE g.payer_group = quotes.payer_group AND g.approved_at >= ? "',
        "\"FROM quotes AS g WHERE g.payer_group = 'none' AND g.approved_at >= ? \"",
        GROUPS,
    ),
    Mutation(
        "a quote keeps the group it was made in",
        LEDGER_FILE,
        "                self.owner(),\n                current_group(),",
        '                self.owner(),\n                "",',
        GROUPS,
    ),
    Mutation(
        "the group comes from its header",
        f"{SRC}/http.py",
        "            acting.enter_context(acting_for(owner, group))",
        "            acting.enter_context(acting_for(owner))",
        GROUPS,
    ),
    host(
        "a PACT agent's chat held as itself pays in the agent's group",
        "pact/conversation.py",
        "_chat(brand, caller.owner, caller.payer_group)",
        "_chat(brand, caller.owner)",
        ["tests/test_pact.py"],
    ),
    host(
        "a call made inside a payer group names it",
        "turns/hub.py",
        "            if group := _payer_group.get():",
        "            if group := '':",
        ["tests/test_hub.py"],
    ),
    host(
        "a chat's turns run inside its payer group",
        "turns/chat_core.py",
        "                    paying_as(await self._payer_group()),\n                ):\n",
        "                    paying_as(''),\n                ):\n",
        ["tests/test_turn_resilience.py"],
    ),
    Mutation(
        "a quote's group never changes after it is made (database trigger)",
        "migrations/0007_payer_group.sql",
        "created_at, expires_at, owner, payer_group ON quotes",
        "created_at, expires_at, owner ON quotes",
        GROUPS,
    ),
]
