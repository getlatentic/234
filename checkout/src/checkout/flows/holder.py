# SPDX-License-Identifier: AGPL-3.0-or-later
"""The name the bank holds an account under: one lookup, for a transfer quote and for a saved recipient."""

from ..paystack.api import AccountLookup, PaystackApi, PaystackError
from .provider_error import as_domain_error


async def account_holder(paystack: PaystackApi, account_number: str, bank_code: str) -> str:
    try:
        return await paystack.resolve_account(AccountLookup(account_number, bank_code))
    except PaystackError as error:
        raise as_domain_error(error, "look up that account") from error
