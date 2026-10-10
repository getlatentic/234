# SPDX-License-Identifier: AGPL-3.0-or-later
"""Airtime and data delivery through VTpass."""

from tools.mutations.model import (
    AIRTIME,
    SRC,
    Mutation,
)

MUTATIONS: list[Mutation] = [
    Mutation(
        "airtime is delivered only after the payment is confirmed",
        f"{SRC}/flows/airtime.py",
        'if checked.paid and quote.state == "approved":',
        'if quote.state == "approved":',
        AIRTIME,
    ),
    Mutation(
        "VTpass is asked once however many callers verify together",
        f"{SRC}/flows/airtime.py",
        "if not await ledger.acquire_step(quote.id, STEP_STALE_MS):\n            return await "
        "ledger.require(quote.id, self.connector)",
        "if False:\n            return await ledger.require(quote.id, self.connector)",
        AIRTIME,
    ),
    Mutation(
        "the VTpass request id is chosen once per quote",
        f"{SRC}/flows/airtime.py",
        'if await ledger.set_progress_once(quote.id, "fulfilment", proposed):',
        'if await ledger.patch_progress(quote.id, {"fulfilment": proposed}):',
        AIRTIME,
    ),
    Mutation(
        "a pending order is requeried, not ordered again",
        f"{SRC}/flows/airtime.py",
        'if fulfilment["attempts"] == 0:',
        "if True:",
        AIRTIME,
    ),
    Mutation(
        "a request id VTpass never saw is ordered again, not left pending",
        f"{SRC}/flows/airtime.py",
        "if outcome.unknown_request else outcome",
        "if False else outcome",
        AIRTIME,
    ),
    Mutation(
        "an outcome arriving after the quote moved on is not recorded",
        f"{SRC}/flows/airtime.py",
        'return await ledger.patch_progress(quote_id, patch, only_state="approved")',
        "return await ledger.patch_progress(quote_id, patch)",
        AIRTIME,
    ),
    Mutation(
        "a paid order VTpass could not deliver is a refund due",
        f"{SRC}/flows/airtime.py",
        'quote_id, ("approved",), "refund_due", {**patch, "failureReason": reason}',
        'quote_id, ("approved",), "settled", {**patch, "failureReason": reason}',
        AIRTIME,
    ),
    Mutation(
        "no quote is made when VTpass would not deliver",
        f"{SRC}/flows/airtime.py",
        "        if not access.ok:",
        "        if False:",
        AIRTIME,
    ),
    Mutation(
        "no quote is made for an order the VTpass wallet cannot cover",
        f"{SRC}/flows/airtime.py",
        "if access.balance_kobo is not None and access.balance_kobo < amount_kobo:",
        "if False:",
        AIRTIME,
    ),
    Mutation(
        "the limits are checked before VTpass is asked",
        f"{SRC}/flows/airtime.py",
        "        await ledger.assert_quotable(new.amount_kobo)\n        await self._assert_vtpass_ready",
        "        await self._assert_vtpass_ready",
        AIRTIME,
    ),
    Mutation(
        "an unclear VTpass reply is pending, never failed",
        f"{SRC}/vtpass/interpret.py",
        'return VtpassOutcome("failed", code, description)\n    return VtpassOutcome("pending", code, '
        "description)",
        'return VtpassOutcome("failed", code, description)\n    return VtpassOutcome("failed", code, '
        "description)",
        ["tests/test_vtpass_interpret.py", "tests/test_vtpass_client.py"],
    ),
    Mutation(
        "refused VTpass credentials are a refusal, not a pending order",
        f"{SRC}/vtpass/interpret.py",
        "if http_status in REFUSED_STATUSES:",
        "if False:",
        ["tests/test_vtpass_interpret.py", "tests/test_vtpass_client.py"],
    ),
    Mutation(
        "a dropped VTpass connection is pending, never failed",
        f"{SRC}/vtpass/client.py",
        'return no_confirmation("no reply")',
        'return VtpassOutcome("failed", None, "no reply")',
        ["tests/test_vtpass_client.py"],
    ),
    Mutation(
        "a refused balance check stops the purchase checks",
        f"{SRC}/vtpass/client.py",
        "if reply.status in (401, 403):\n            return AccessCheck",
        "if False:\n            return AccessCheck",
        ["tests/test_vtpass_client.py"],
    ),
]
