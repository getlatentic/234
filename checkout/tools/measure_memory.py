# SPDX-License-Identifier: AGPL-3.0-or-later
"""How long the memory index takes to build, against a running connectors Worker and its local D1.

    cd checkout && CHECKOUT_URL=http://localhost:8920 uv run python -m tools.measure_memory [entries]

It saves `entries` notes (200 by default, the cap) for one owner through the same two calls a person's Save
makes, then times the `memory_index` tool, which is the one query behind the index and its rendering, for that
owner and for an owner with no notes (the cost of the HTTP call and the Worker alone). Times are of the whole
call from the client, in milliseconds, one after the other; the table docs/memory.md quotes is this output."""

import asyncio
import statistics
import sys
import time

import httpx

from tests.worker_client import BASE_URL, Mcp

FULL = "c4" * 16
EMPTY = "d5" * 16
ROUNDS = 300
WARMUP = 20
HOOK = (
    "a hook of a hundred and twenty characters, near the limit of one line in the memory index of a person x"
)
HEADER = "x-memory-owner"


class Notes(Mcp):
    async def rpc(self, method, params=None):
        self.http.headers[HEADER] = self.owner
        return await super().rpc(method, params)


def percentile(ordered: list[float], share: float) -> float:
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))]


def summary(values: list[float]) -> str:
    ordered = sorted(values)
    return f"{statistics.median(ordered):.1f} / {percentile(ordered, 0.95):.1f} / {ordered[-1]:.1f}"


async def fill(notes: Notes, entries: int) -> None:
    for number in range(entries):
        kinds = ("fact", "preference")
        made = await notes.call(
            "remember",
            kind=kinds[number % 2],
            title=f"Note number {number}",
            hook=HOOK[:110],
            body=f"Body {number}.",
        )
        await notes.call(
            "confirm_memory",
            proposal_id=made["structuredContent"]["proposal_id"],
            confirm_token=made["_meta"]["confirmToken"],
        )


async def timed(notes: Notes, tool: str, **arguments) -> list[float]:
    for _ in range(WARMUP):
        await notes.call(tool, **arguments)
    took = []
    for _ in range(ROUNDS):
        started = time.perf_counter()
        await notes.call(tool, **arguments)
        took.append((time.perf_counter() - started) * 1000)
    return took


async def main(entries: int) -> None:
    async with httpx.AsyncClient(timeout=60) as http:
        await http.post(f"{BASE_URL}/test/reset")
        full, empty = Notes(http, "memory", FULL), Notes(http, "memory", EMPTY)
        await fill(full, entries)
        index = (await full.call("memory_index"))["structuredContent"]
        print(
            f"{entries} notes saved; the index shows {index['entries']} of them in {index['tokens']} tokens"
        )
        print("median / p95 / max, ms, over", ROUNDS, "calls")
        print("| call | median / p95 / max |\n|---|---|")
        print(f"| memory_index, {entries} notes | {summary(await timed(full, 'memory_index'))} |")
        print(f"| memory_index, no notes | {summary(await timed(empty, 'memory_index'))} |")
        searched = summary(await timed(full, "recall", query="note number"))
        print(f"| recall by words, {entries} notes | {searched} |")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 200))
