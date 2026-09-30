# SPDX-License-Identifier: AGPL-3.0-or-later
"""The key the connectors scope a person's money by.

A chat belongs to a visitor (`v:<id>`, the id from the signed cookie), to a signed-in account (`u:<32 hex>`,
accounts/owner.py) or to an A2A agent (`a:<name>`). The connectors take an opaque key of 32 lowercase hex
characters: a visitor's id as it is, anyone else's a digest of their owner string, so an account and an
agent have an allowance of their own too and no name can collide with a visitor's id. The key comes from the
chat's owner as stored, never from a request: whoever is let into a chat by its share link spends the chat
owner's allowance, as the chat owner's model calls do.
"""

import hashlib
import re

VISITOR = re.compile(r"v:([0-9a-f]{32})")


def ledger_owner(chat_owner: str) -> str:
    found = VISITOR.fullmatch(chat_owner)
    return found[1] if found else hashlib.sha256(chat_owner.encode()).hexdigest()[:32]
