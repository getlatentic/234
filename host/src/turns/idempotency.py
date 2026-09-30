# SPDX-License-Identifier: AGPL-3.0-or-later
"""The key a quote-making tool call carries to the connectors' ledger.

The model does not manage keys: it is not offered the field. The host derives one per tool call from whose
money it is, the chat and the call's own id, which the log records. A call that is run again after a
restart has the same id and so the same key, and the ledger hands back the quote it already made; a new
request, in this chat or another, is a new call and gets a new key.

The key is a digest: opaque, 40 lowercase hex characters, inside what the connectors accept
(8 to 64 of letters, digits, dot, dash, underscore, colon).
"""

import hashlib
import json

FIELD = "idempotency_key"
_DOMAIN = "quote-call"
_LENGTH = 40


def derive_key(owner: str, chat_id: str, call_id: str) -> str:
    material = json.dumps([_DOMAIN, owner, chat_id, call_id], separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()[:_LENGTH]
