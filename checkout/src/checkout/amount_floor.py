# SPDX-License-Identifier: AGPL-3.0-or-later
"""The smallest amount any quote may be for, whoever asks and however it is worded.

Sources, read 2026-09-30 (Paystack's documentation through Context7; VTpass's at vtpass.com/documentation):
- Paystack states only that a transaction amount must be an integer greater than zero, that Pay with Transfer
  needs at least NGN 100, and that NGN 50 is the recommended least for a card's first charge, since banks
  and card brands may refuse less. It documents no minimum for a transfer.
- VTpass documents no minimum for airtime or data; `amount` is "mandatory, a number" and its examples start
  at 20.
So no provider states a product minimum above NGN 50, and the floor is NGN 50: the smallest airtime people
buy, and above the amounts (a kobo, a naira) that only a mistake or an injected instruction asks for.
"""

from .errors import DomainError
from .money import Kobo, format_naira

MINIMUM_KOBO: Kobo = 5_000


def assert_above_floor(amount_kobo: Kobo) -> None:
    if amount_kobo < MINIMUM_KOBO:
        raise DomainError(
            "AMOUNT_TOO_SMALL",
            f"The smallest amount is {format_naira(MINIMUM_KOBO)}. {format_naira(amount_kobo)} is below it, "
            f"so nothing was quoted. Ask the person for an amount of {format_naira(MINIMUM_KOBO)} or more.",
        )
