# SPDX-License-Identifier: AGPL-3.0-or-later
"""Repeats the daily-limit race many times and prints how often each approval strategy overspends.

usage: uv run python -m tests.stress [rounds]
"""

import asyncio
import sys

import httpx

from tests.worker_client import BASE_URL, Mcp, quote_args, quote_of

LIMIT = 10_000_000
EACH = 3_000_000


async def one_round(http: httpx.AsyncClient, worker: Mcp, naive: bool) -> tuple[int, int]:
    await http.post(f"{BASE_URL}/test/reset")
    quotes = []
    for i in range(8):
        made = await worker.call("create_payment_quote", **quote_args(EACH, "₦30,000", f"race-{i:08d}"))
        quotes.append((quote_of(made), made["_meta"]["approvalToken"]))
    if naive:
        await asyncio.gather(*[http.post(f"{BASE_URL}/test/naive-approve/{v['id']}") for v, _ in quotes])
    else:
        await asyncio.gather(
            *[
                worker.call("approve_quote", quote_id=v["id"], approval_token=t, displayed_amount_kobo=EACH)
                for v, t in quotes
                for _ in range(3)
            ]
        )
    summary = (await http.get(f"{BASE_URL}/test/summary")).json()
    approved = summary["byState"].get("approved", {"n": 0, "kobo": 0})
    return approved["n"], approved["kobo"]


async def main(rounds: int) -> None:
    async with httpx.AsyncClient(timeout=60, limits=httpx.Limits(max_connections=100)) as http:
        worker = Mcp(http)
        for naive in (False, True):
            counts = [await one_round(http, worker, naive) for _ in range(rounds)]
            over = sum(1 for _, kobo in counts if kobo > LIMIT)
            name = "read-then-write (control)" if naive else "conditional UPDATE"
            print(
                f"{name}: {rounds} rounds, overspent {over}, approved counts {sorted({n for n, _ in counts})}"
            )


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 30))
