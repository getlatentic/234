# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the simulated Paystack calls a bank: its name on Paystack's list, or a placeholder."""

from .bank_names import bank_of_code


def simulated_bank_name(bank_code: str) -> str:
    listed = bank_of_code(bank_code)
    return listed.name if listed else f"Simulated Bank {bank_code}"
