# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each guardrail, the one place that enforces it, and the tests that must notice when it is undone.

`find` must appear exactly once in `file`. A mutation names its project: the connector Worker (the default) or
the Django host, whose tests run in the host's own environment. Guardrails of the TypeScript demo that live in
its React card and its loopback HTTP server have no counterpart here; the card's own rules (full screen,
focus, the sandbox as the browser enforces it) are checked by the browser conformance runs, not by mutation.
"""

from tools.mutations import (
    account_rules,
    airtime_rules,
    compaction_rules,
    config_rules,
    connected_rules,
    cost_rules,
    event_rules,
    host_rules,
    input_rules,
    ledger_rules,
    memory_host_rules,
    memory_rules,
    menu_rules,
    metrics_rules,
    model_choice_rules,
    oauth_rules,
    owner_rules,
    pact_rules,
    payer_group_rules,
    payment_leg,
    provider_hook_rules,
    quote_event_host_rules,
    reach_rules,
    sandbox_rules,
    token_rules,
    transfer_and_food,
    turn_resilience_rules,
    vtpass_number_rules,
)
from tools.mutations.model import Mutation

MUTATIONS: list[Mutation] = [
    *config_rules.MUTATIONS,
    *ledger_rules.MUTATIONS,
    *owner_rules.MUTATIONS,
    *input_rules.MUTATIONS,
    *payment_leg.MUTATIONS,
    *airtime_rules.MUTATIONS,
    *vtpass_number_rules.MUTATIONS,
    *transfer_and_food.MUTATIONS,
    *model_choice_rules.MUTATIONS,
    *menu_rules.MUTATIONS,
    *sandbox_rules.MUTATIONS,
    *host_rules.MUTATIONS,
    *token_rules.MUTATIONS,
    *account_rules.MUTATIONS,
    *compaction_rules.MUTATIONS,
    *memory_rules.MUTATIONS,
    *memory_host_rules.MUTATIONS,
    *oauth_rules.MUTATIONS,
    *event_rules.MUTATIONS,
    *provider_hook_rules.MUTATIONS,
    *quote_event_host_rules.MUTATIONS,
    *pact_rules.MUTATIONS,
    *cost_rules.MUTATIONS,
    *metrics_rules.MUTATIONS,
    *payer_group_rules.MUTATIONS,
    *turn_resilience_rules.MUTATIONS,
    *connected_rules.MUTATIONS,
    *reach_rules.MUTATIONS,
]
