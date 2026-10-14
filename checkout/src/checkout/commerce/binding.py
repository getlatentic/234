# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a person's approval of a basket is bound to (docs/commerce.md, rule 4). The approval token of a
merchant's quote is the ledger's own HMAC (Ledger.approval_token), taken not over the quote's id alone but
over its id and a digest of the merchant, the lines, the fees, the total, the buyer's fields, the holder's
name and the expiry. The digest is read from the stored quote each time, so a token made for a quote that
differs in any of them, or for the quote's id alone, approves nothing."""

import hashlib
import json

from ..ledger import Quote


def quote_digest(quote: Quote) -> str:
    d = quote.details
    terms = {
        "merchant": d["merchantId"],
        "lines": d["lines"],
        "fees": d["fees"],
        "fields": d["fields"],
        "holder": d["holder"],
        "total": quote.amount_kobo,
        "expires": quote.expires_at,
    }
    if d.get("funding"):
        terms["funding"], terms["index"] = d["funding"], d["index"]
    return hashlib.sha256(json.dumps(terms, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def approval_subject(quote: Quote) -> str:
    """The text the ledger's HMAC is taken over for this quote."""
    return f"{quote.id}:{quote_digest(quote)}"
