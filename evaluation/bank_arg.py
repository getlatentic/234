# SPDX-License-Identifier: AGPL-3.0-or-later
"""The bank a transfer call names, as the connector reads it. The model passes `bank` as the person said it
and the connector's table turns it into a code, so a case that expects `bank_code` 058 is met by "GTB",
"Guaranty Trust" and every other spelling the table resolves to 058.

The table is the connector's own (`checkout.paystack.bank_names`, found by `../checkout/src` on the path),
so the scorer and the server agree on what a spelling means; the table has its own tests, written from
Paystack's list, and `tests/test_bank_arg.py` checks the case codes against that list."""

from typing import Any

from checkout.paystack.bank_names import BankNotFound, normalise, resolve_bank


def _in_their_words(bank: str, said: str) -> bool:
    return normalise(bank) in normalise(said)


def with_resolved_bank(arguments: dict[str, Any], said: str) -> dict[str, Any]:
    """The call's arguments with `bank_code` the code the connector would resolve `bank` to. A bank the table
    cannot resolve leaves no `bank_code` when it is in the person's words (the connector refuses it, and
    nobody was given a wrong bank); one that is not in their words becomes an invented code, which is a
    wrong recipient."""
    bank = arguments.get("bank")
    if not isinstance(bank, str) or not bank.strip():
        return arguments
    rest = {k: v for k, v in arguments.items() if k not in ("bank", "bank_code")}
    try:
        return {**rest, "bank_code": resolve_bank(bank).code}
    except BankNotFound:
        return rest if _in_their_words(bank, said) else {**rest, "bank_code": f"unresolved bank {bank!r}"}
