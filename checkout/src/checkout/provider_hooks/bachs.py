# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /hooks/bachs: a top-up's money arriving. Unlike Paystack's webhook, this one is acted on at once, and
only once it is proven Bachs': a forged, replayed or future-dated delivery is refused before its body is read.

Bachs retries anything but a 2xx, and stops on a 400 (https://docs.bachs.io/guides/webhooks/overview), so:
a delivery that fails the signature is answered 400; a genuine one is answered 2xx only once its `fund`
entry exists, or once it is known never to credit (an unknown reference, a mismatch, another event), and a
credit the cap refused today is answered 503 so Bachs delivers it again after the wallet has spent."""

from dataclasses import dataclass

from ..audit import Audit
from ..bachs.events import collection_of
from ..bachs.signature import SIGNATURE_HEADER, Verdict, check
from ..clock import Clock
from ..responses import HttpResponse, json_response
from ..wallet.topup_credit import Outcome, TopUpCredit

MAX_BODY = 64 * 1024


@dataclass(frozen=True)
class BachsHook:
    credit: TopUpCredit
    secrets: tuple[str, ...]
    clock: Clock
    audit: Audit

    async def answer(self, headers: dict[str, str], raw: bytes) -> HttpResponse:
        if len(raw) > MAX_BODY:
            return HttpResponse(413, "Too large")
        verdict = check(raw, headers.get(SIGNATURE_HEADER, ""), self.secrets, self.clock.now())
        if verdict is not Verdict.GENUINE:
            self.audit.log("bachs.webhook.refused", reason=str(verdict))
            return HttpResponse(400, "Refused")
        collection = collection_of(raw)
        if collection is None:
            return json_response({"received": True})
        if await self.credit.settle(collection) is Outcome.OVER_CAP:
            return HttpResponse(503, "Not credited yet")
        return json_response({"received": True})
