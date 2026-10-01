# SPDX-License-Identifier: AGPL-3.0-or-later
"""A saved recipient is what the bank says, never what the model typed: the bank is the one on Paystack's list
that the name fits (ambiguity is a refusal), the account name is the bank's answer for that account, and only
then is anything shown to the person or saved. The lookup is the one a transfer quote makes."""

import re
from dataclasses import dataclass
from typing import Any

from ..flows.bank_choice import choose_bank
from ..flows.holder import account_holder
from ..flows.inputs import clean_account
from ..paystack.api import PaystackApi
from .fields import HOOK_MAX, clean_name

_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class Holder:
    account_number: str
    bank_code: str
    bank_name: str
    account_name: str

    @property
    def ends(self) -> str:
        return self.account_number[-4:]

    @property
    def hook(self) -> str:
        """The index line of a recipient: the bank's own words, with only the last four digits."""
        tail = f", ends {self.ends}"
        head = f"{self.bank_name}, "
        return f"{head}{self.account_name[: HOOK_MAX - len(head) - len(tail)].rstrip()}{tail}"

    def fields(self) -> dict[str, Any]:
        return {
            "bank_code": self.bank_code,
            "account_number": self.account_number,
            "account_name": self.account_name,
        }


async def resolve_holder(paystack: PaystackApi, account_number: str, bank: str) -> Holder:
    """Raises a refusal when the bank is not exactly one bank or the account does not resolve."""
    account = clean_account(account_number)
    chosen = choose_bank(bank, None)
    name = clean_name(await account_holder(paystack, account, chosen.code))
    return Holder(account, chosen.code, chosen.name or chosen.code, name)


def same_name(first: str, second: str) -> bool:
    """Whether two renderings of an account holder's name are the same name: the same words, in any order."""
    return sorted(_WORD.findall(first.casefold())) == sorted(_WORD.findall(second.casefold()))
