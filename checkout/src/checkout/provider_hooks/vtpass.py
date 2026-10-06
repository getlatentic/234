# SPDX-License-Identifier: AGPL-3.0-or-later
"""VTpass's `transaction-update` callback. It is not signed, so it is only a hint to requery; VTpass sends it
again until the answer is `{"response": "success"}`
(https://vtpass.com/documentation/transaction-update-webhook-api/)."""

import json

from .references import quote_id_in

ACKNOWLEDGED = {"response": "success"}


def quote_of(body: bytes) -> str | None:
    try:
        update = json.loads(body)
    except ValueError:
        return None
    if not isinstance(update, dict) or update.get("type") != "transaction-update":
        return None
    data = update.get("data")
    if not isinstance(data, dict):
        return None
    return quote_id_in(data.get("requestId"))
