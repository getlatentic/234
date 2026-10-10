# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one approval of a quote, putting it back, and the token that lets a card ask for it.

* one approval per quote: `state = 'open'` in the UPDATE's WHERE;
* the daily limit, per owner: the SUM of that owner's approved spend today is a subquery of that same
  UPDATE, so the check and the reservation are one atomic statement and two approvals cannot both fit;
  another owner's spend is not in the sum, and another owner's quote is not in the WHERE.

A batch is one D1 transaction; the approval and its event row travel in one.
"""

import hashlib
import hmac
import json

from ..clock import lagos_day_start
from ..errors import DomainError
from .making import QuoteMaking
from .records import SPENDING_SQL, ClaimTerms, Quote


def _claim_sql(funded: ClaimTerms) -> str:
    return (
        "UPDATE quotes SET state = 'approved', approved_at = ?, "
        "progress = json_patch(progress, ?) "
        "WHERE id = ? AND owner = ? AND connector = ? AND state = 'open' AND expires_at > ? "
        "AND amount_kobo <= ? AND amount_kobo + (SELECT COALESCE(SUM(amount_kobo), 0) "
        f"FROM quotes WHERE owner = ? AND approved_at >= ? AND state IN ({SPENDING_SQL})) <= ? "
        "AND (payer_group = '' OR amount_kobo + (SELECT COALESCE(SUM(g.amount_kobo), 0) "
        "FROM quotes AS g WHERE g.payer_group = quotes.payer_group AND g.approved_at >= ? "
        f"AND g.state IN ({SPENDING_SQL})) <= ?) AND ({funded.condition})"
    )


class Approvals(QuoteMaking):
    async def claim_approval(
        self, quote_id: str, connector: str, terms: ClaimTerms | None = None
    ) -> tuple[Quote, bool]:
        """The one approval a quote can have. A later claim finds the first and changes nothing.

        The UPDATE holds every rule: the caller's own quote, still open, not expired, within the
        per-payment limit, the caller's approved spend today plus this quote within the daily limit,
        and, for a quote made in a payer group, the group's approved spend today plus this quote within
        the group's limit, and the funding source's `terms`. The event row rides in the same batch,
        inserted only when the UPDATE changed a row.
        """
        now, owner = self._clock.now(), self.owner()
        funded = terms or ClaimTerms({}, "1")
        results = await self._db.batch(
            [
                (
                    _claim_sql(funded),
                    (
                        now,
                        json.dumps(funded.progress),
                        quote_id,
                        owner,
                        connector,
                        now,
                        self.limits.per_payment_kobo,
                        owner,
                        lagos_day_start(now),
                        self.limits.daily_kobo,
                        lagos_day_start(now),
                        self.limits.group_daily_kobo,
                    ),
                ),
                (
                    "INSERT INTO quote_events (quote_id, event, seq, at) "
                    "SELECT ?, 'approval.claimed', 1 + (SELECT COUNT(*) FROM quote_events "
                    "WHERE quote_id = ? AND event = 'approval.released'), ? WHERE changes() = 1",
                    (quote_id, quote_id, now),
                ),
            ]
        )
        if results[0].changes == 1:
            return await self._must_get(quote_id), True
        return await self._why_not_approved(quote_id, connector)

    async def _why_not_approved(self, quote_id: str, connector: str) -> tuple[Quote, bool]:
        quote = await self.require(quote_id, connector)
        if quote.approved_at is not None:
            return quote, False
        if quote.state == "expired":
            raise DomainError("QUOTE_EXPIRED", "This quote has expired. Ask for a new quote.")
        if quote.state != "open":
            raise DomainError("QUOTE_NOT_OPEN", f"This quote is {quote.state} and cannot be approved.")
        self._assert_within_per_payment(quote.amount_kobo)
        self._assert_within_daily(quote.amount_kobo, (await self.budget()).spent_today_kobo)
        await self._assert_within_group(quote.amount_kobo, await self._group_of(quote_id))
        raise DomainError("APPROVAL_IN_PROGRESS", "The quote changed while it was being approved.")

    async def release_approval(self, quote_id: str) -> Quote:
        """Puts an approval back when the provider never took the request, and records that it was."""
        await self._db.batch(
            [
                (
                    "UPDATE quotes SET state = 'open', approved_at = NULL WHERE id = ? AND owner = ? "
                    "AND state = 'approved' "
                    "AND json_extract(progress, '$.checkoutUrl') IS NULL",
                    (quote_id, self.owner()),
                ),
                (
                    "INSERT INTO quote_events (quote_id, event, seq, at) "
                    "SELECT ?, 'approval.released', 1 + (SELECT COUNT(*) FROM quote_events "
                    "WHERE quote_id = ? AND event = 'approval.released'), ? WHERE changes() = 1",
                    (quote_id, quote_id, self._clock.now()),
                ),
            ]
        )
        return await self._must_get(quote_id)

    def approval_token(self, quote_id: str) -> str:
        return hmac.new(self._secret, quote_id.encode(), hashlib.sha256).hexdigest()

    def check_approval_token(self, quote_id: str, token: str) -> bool:
        return hmac.compare_digest(self.approval_token(quote_id), token)
