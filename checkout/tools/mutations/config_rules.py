# SPDX-License-Identifier: AGPL-3.0-or-later
"""Keys, modes and settings: what the server refuses to start with."""

from tools.mutations.model import (
    CONFIG,
    SRC,
    Mutation,
)

MUTATIONS: list[Mutation] = [
    Mutation(
        "a live Paystack key is refused at startup",
        f"{SRC}/config.py",
        '(env.text(name) or "").startswith("sk_live_")',
        "False",
        CONFIG,
    ),
    Mutation(
        "only sk_test_ keys are accepted",
        f"{SRC}/config.py",
        "if key is not None and not _TEST_KEY.fullmatch(key):",
        "if False:",
        CONFIG,
    ),
    Mutation(
        "the Paystack client refuses a live key",
        f"{SRC}/paystack/client.py",
        'if not secret_key.startswith("sk_test_"):',
        "if False:",
        ["tests/test_paystack_client.py"],
    ),
    Mutation(
        "real Paystack mode for any connector needs the test key",
        f"{SRC}/config.py",
        "if any_real and key is None:",
        "if False:",
        CONFIG,
    ),
    Mutation(
        "sandbox VTpass mode needs all three credentials",
        f"{SRC}/config.py",
        'if mode == "sandbox" and credentials is None:',
        "if False:",
        CONFIG,
    ),
    Mutation(
        "the per-payment limit cannot exceed the daily limit",
        f"{SRC}/config.py",
        "if per_payment > daily:",
        "if False:",
        CONFIG,
    ),
    Mutation(
        "VTpass is only called on the sandbox host",
        f"{SRC}/vtpass/client.py",
        'VTPASS_SANDBOX_URL = "https://sandbox.vtpass.com/api"',
        'VTPASS_SANDBOX_URL = "https://vtpass.com/api"',
        ["tests/test_vtpass_client.py"],
    ),
    Mutation(
        "each connector runs in its own Paystack mode",
        f"{SRC}/app.py",
        "mode = settings.paystack.mode_for(connector)",
        "mode = settings.paystack.mode",
        ["tests/test_app_wiring.py"],
    ),
]
