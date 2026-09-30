# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who a quote is for, shortened: the audit log shows which number or account without holding it in full."""

import re

_LOCAL_MOBILE = re.compile(r"^0\d{10}$")


def mask_phone(phone: str) -> str:
    if len(phone) <= 7:
        return "*" * max(len(phone) - 2, 0) + phone[-2:]
    return f"{phone[:4]}{'*' * (len(phone) - 7)}{phone[-3:]}"


def mask_account(account: str) -> str:
    return "*" * max(len(account) - 4, 0) + account[-4:]


def group_phone(phone: str) -> str:
    """0803 123 4567, for reading a number back to a person."""
    if _LOCAL_MOBILE.fullmatch(phone):
        return f"{phone[:4]} {phone[4:7]} {phone[7:]}"
    return phone
