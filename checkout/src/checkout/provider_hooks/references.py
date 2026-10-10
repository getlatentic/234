# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every reference the connectors give a provider holds the quote id: `qt-…-a1` for a checkout,
`trf-qt-…` for a transfer, and the VTpass request id ends with it (ids.py, vtpass/request_id.py). A wallet
withdrawal's transfer is referenced by the withdrawal id itself, `wd-…`."""

import re

QUOTE_ID = re.compile(r"qt-[0-9a-f]{20}")
WITHDRAWAL_ID = re.compile(r"wd-[0-9a-f]{20}")


def quote_id_in(reference: object) -> str | None:
    found = QUOTE_ID.search(reference) if isinstance(reference, str) else None
    return found[0] if found else None


def withdrawal_id_in(reference: object) -> str | None:
    """The withdrawal a transfer reference is, when it is exactly one."""
    return reference if isinstance(reference, str) and WITHDRAWAL_ID.fullmatch(reference) else None


def is_withdrawal_id(subject: str | None) -> bool:
    return withdrawal_id_in(subject) is not None
