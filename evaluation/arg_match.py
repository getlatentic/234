# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether the arguments of a call are the ones a case accepts, written as the person might have written
them: a phone with a plus or dashes, an account with spaces, a bank by any name the connector resolves.
Pure."""

import re
from typing import Any

from .bank_arg import with_resolved_bank


def digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value))


def phone_of(value: Any) -> str:
    number = digits(value)
    return "0" + number[3:] if number.startswith("234") and len(number) == 13 else number


def words_of(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", "", str(value).lower().replace("'", "")).split())


def arg_matches(name: str, want: Any, got: Any) -> bool:
    match name:
        case "amount_kobo":
            return isinstance(got, int | float) and not isinstance(got, bool) and got == want
        case "phone":
            return phone_of(got) == phone_of(want)
        case "account_number":
            return digits(got) == digits(want)
        case "merchant":
            return words_of(want) in words_of(got)
        case "network":
            return str(got).lower() == want
        case _:
            return isinstance(got, str) and got.strip() == str(want)


def arguments_of(call: dict[str, Any], said: str) -> dict[str, Any]:
    """What the call asks for, the bank resolved to its code."""
    return with_resolved_bank(call["arguments"], said)


BY_HAND = ("account_number", "bank_code")


def arg_problems(want: dict[str, Any], call: dict[str, Any], said: str) -> list[str]:
    given = arguments_of(call, said)
    problems = [
        f"{name} is {given.get(name)!r}, expected {value!r}"
        for name, value in want.items()
        if not arg_matches(name, value, given.get(name))
    ]
    if "recipient_memory_id" in want:
        problems += [f"{name} was given for a saved recipient" for name in BY_HAND if name in given]
    return problems
