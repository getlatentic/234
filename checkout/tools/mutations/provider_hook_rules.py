# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider webhooks: Paystack's must carry its signature, a webhook rechecks only a pending quote and only
as its owner, and the minute expires overdue quotes so their endings are told."""

from tools.mutations.model import SRC, Mutation

HOOKS = ["tests/test_provider_hooks.py"]

MUTATIONS: list[Mutation] = [
    Mutation(
        "a Paystack webhook must carry Paystack's signature",
        f"{SRC}/provider_hooks/http.py",
        "    if not any(paystack.is_genuine(raw, signature, key) for key in keys):",
        "    if False:",
        HOOKS,
    ),
    Mutation(
        "a recheck acts as the quote's owner",
        f"{SRC}/provider_hooks/rechecks.py",
        '        with acting_for(row["owner"]):',
        "        with acting_for(ALICE_FOR_EVERYONE):",
        HOOKS,
    ),
    Mutation(
        "the minute expires overdue quotes",
        f"{SRC}/provider_hooks/rechecks.py",
        "\"UPDATE quotes SET state = 'expired' WHERE state = 'open' AND expires_at <= ?\"",
        "\"UPDATE quotes SET state = state WHERE state = 'open' AND expires_at <= ?\"",
        HOOKS,
    ),
]
