# SPDX-License-Identifier: AGPL-3.0-or-later
"""VTpass's `transaction-update` callback. It is not signed, so it is only a hint to requery; VTpass sends it
again until the answer is `{"response": "success"}`
(https://vtpass.com/documentation/transaction-update-webhook-api/). The same callback with code 040 and status
`reversed` says VTpass took back an order it had reported delivered; that too is only a hint."""

import json
from typing import Any

from .references import quote_id_in

ACKNOWLEDGED = {"response": "success"}


def _data_of(body: bytes) -> dict[str, Any] | None:
    try:
        update = json.loads(body)
    except ValueError:
        return None
    if not isinstance(update, dict) or update.get("type") != "transaction-update":
        return None
    data = update.get("data")
    return data if isinstance(data, dict) else None


def quote_of(body: bytes) -> str | None:
    data = _data_of(body)
    return quote_id_in(data.get("requestId")) if data else None


def says_reversed(body: bytes) -> bool:
    """Whether the callback reports a reversal: code 040, or status `reversed`."""
    data = _data_of(body) or {}
    content = data.get("content")
    transactions = content.get("transactions") if isinstance(content, dict) else None
    status = transactions.get("status") if isinstance(transactions, dict) else None
    return data.get("code") == "040" or status == "reversed"
