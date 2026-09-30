# SPDX-License-Identifier: AGPL-3.0-or-later
"""The number VTpass is sent as the one to top up, decided from the mode and the number the person typed.
Everything the person and the model see keeps the number as typed."""

from .phone import DOCUMENTED_SUCCESS_NUMBER, SANDBOX_SCENARIO_NUMBERS, SIMULATED_FAILURE_NUMBER

# What a number typed on purpose to reach a scenario looks like: the documented triggers, and the
# simulator's number for failure (the sandbox fails it like any number it does not know).
TRIGGER_NUMBERS = SANDBOX_SCENARIO_NUMBERS | {DOCUMENTED_SUCCESS_NUMBER, SIMULATED_FAILURE_NUMBER}


def number_for_vtpass(mode: str, typed: str) -> str:
    """The real sandbox delivers only to its success number, so a real number typed by a person would fail
    every order there: in `sandbox` mode VTpass is sent that number instead, and nothing reaches the
    person's phone. A trigger number goes unchanged, so pending and failure stay demonstrable. `simulated`
    sends the typed number to the simulator, which decides for itself, and `live` would send it as typed."""
    match mode:
        case "sandbox":
            return typed if typed in TRIGGER_NUMBERS else DOCUMENTED_SUCCESS_NUMBER
        case "simulated" | "live":
            return typed
        case _:
            raise ValueError(f"Unknown VTpass mode: {mode}")
