# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which bank a transfer goes to: the name the person gave, turned into Paystack's code by the bank table.

The model passes the bank as the person said it. A code some other client sends is accepted too, and must
agree with the name when both come. A name that is not exactly one bank is refused, never guessed."""

import re
from typing import NamedTuple

from ..errors import DomainError
from ..paystack.bank_names import Bank, BankAmbiguous, BankNotFound, bank_of_code, resolve_bank
from .inputs import clean_text

_NUMERIC_CODE = re.compile(r"\d{3,6}")
_NAME_CHARS = 60


class ChosenBank(NamedTuple):
    code: str
    name: str | None


def _some(candidates: tuple[Bank, ...]) -> str:
    names = [bank.name for bank in candidates]
    return ", ".join(names[:-1]) + f" or {names[-1]}" if len(names) > 1 else names[0]


def _resolved(asked: str) -> Bank:
    try:
        return resolve_bank(asked)
    except BankAmbiguous as error:
        raise DomainError(
            "BANK_AMBIGUOUS",
            f'"{asked}" fits more than one bank: {_some(error.candidates)}. Nothing was quoted. '
            "Ask the person which bank it is.",
        ) from error
    except BankNotFound as error:
        near = f" The nearest are {_some(error.candidates)}." if error.candidates else ""
        raise DomainError(
            "BANK_UNKNOWN",
            f'"{asked}" is not a bank on Paystack\'s list.{near} Nothing was quoted. '
            "Ask the person which bank it is.",
        ) from error


def _stated_code(bank_code: str) -> str:
    code = bank_code.strip()
    if not (bank_of_code(code) or _NUMERIC_CODE.fullmatch(code)):
        raise DomainError("INVALID_INPUT", "bank_code is the bank's code, for example 057 for Zenith Bank.")
    return code


def _mismatch(stated: str, asked: str, chosen: Bank) -> DomainError:
    listed = bank_of_code(stated)
    return DomainError(
        "BANK_MISMATCH",
        f"bank_code {stated} ({listed.name if listed else 'no bank on the list'}) is not the bank named, "
        f'"{asked}" ({chosen.name}, code {chosen.code}). Nothing was quoted. '
        "Ask the person which bank it is.",
    )


def choose_bank(bank: str | None, bank_code: str | None) -> ChosenBank:
    stated = None if bank_code is None else _stated_code(bank_code)
    if bank is None or not bank.strip():
        if stated is None:
            raise DomainError(
                "INVALID_INPUT",
                'bank is needed: the bank as the person named it, for example "GTBank". '
                "If they named none, ask which bank.",
            )
        listed = bank_of_code(stated)
        return ChosenBank(stated, listed.name if listed else None)
    asked = clean_text(bank, "bank", _NAME_CHARS)
    chosen = _resolved(asked)
    if stated is not None and stated != chosen.code:
        raise _mismatch(stated, asked, chosen)
    return ChosenBank(chosen.code, chosen.name)
