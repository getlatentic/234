# SPDX-License-Identifier: AGPL-3.0-or-later
Kobo = int
KOBO_PER_NAIRA = 100


def format_naira(kobo: Kobo) -> str:
    sign = "-" if kobo < 0 else ""
    naira, rest = divmod(abs(kobo), KOBO_PER_NAIRA)
    fraction = "" if rest == 0 else f".{rest:02d}"
    return f"{sign}₦{naira:,}{fraction}"
