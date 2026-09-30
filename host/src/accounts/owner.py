# SPDX-License-Identifier: AGPL-3.0-or-later
"""The owner of a signed-in person: a stable key from their Firebase uid.

`u:` and 32 hex characters of HMAC-SHA256 over the uid, keyed with ACCOUNT_KEY. The connectors take an
opaque 32-hex key for whose money a call touches (`turns/ledger_owner.py` derives it from this string), so the
per-owner daily allowance applies to an account unchanged, and the same uid on two devices is one owner with
one set of chats. ACCOUNT_KEY is a key of its own, not DJANGO_SECRET_KEY: rotating the Django key (a routine
act that signs everyone out) must not orphan anyone's chats.
"""

import hashlib
import hmac

PREFIX = "u:"


def account_owner(uid: str, key: str) -> str:
    digest = hmac.new(key.encode(), f"account-owner:{uid}".encode(), hashlib.sha256).hexdigest()
    return f"{PREFIX}{digest[:32]}"
