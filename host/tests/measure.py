# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measurements behind the choice of turn runner and transport, against the running Workers. It is a script,
not a test: `uv run python -m tests.measure` prints the tables that docs/durable-chat.md quotes.

* start: the time from sending a message to its turn starting, on a new chat (a new Durable Object, cold)
  and on a chat that has just run (warm), per runner.
* delivery: the time from an event being stored (its own timestamp) to a client having it, over server-sent
  events (polling the log) and over the WebSocket (push from the Durable Object).
"""

import asyncio
import statistics
import time

from .worker_client import Visitor, finished, reset_budget, runner_urls, ws_events

ROUNDS = 8
STREAM_TURN = "slow:120@0.05"


def summary(values: list[float]) -> str:
    if not values:
        return "n/a"
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return f"{statistics.median(ordered):.0f} / {p95:.0f} ms (n={len(ordered)})"


async def first_event_after(v: Visitor, chat: str, type_: str, since: int) -> float:
    """Milliseconds from now until an event of this type after `since` reaches an SSE reader."""
    started = time.monotonic()
    async for event in v.sse(chat, since):
        if event["type"] == type_:
            return (time.monotonic() - started) * 1000
    raise RuntimeError("the stream ended")


async def start_latency(base: str) -> tuple[list[float], list[float]]:
    cold, warm = [], []
    for _ in range(ROUNDS):
        async with Visitor(base) as v:
            chat = await v.new_chat()
            for bucket, text in ((cold, "hello"), (warm, "hello again")):
                since = (await v.log(chat))[-1]["seq"] if bucket is warm else 0
                started = time.monotonic()
                waiting = asyncio.ensure_future(first_event_after(v, chat, "turn.started", since))
                await v.send(chat, text)
                await waiting
                bucket.append((time.monotonic() - started) * 1000)
                async for event in v.sse(chat, since):
                    if finished(event):
                        break
    return cold, warm


async def delivery_latency(v: Visitor, chat: str, via: str) -> list[float]:
    """Stored-to-received time of the streamed text of one long reply. Server and client share a clock."""
    delays: list[float] = []

    def note(event: dict) -> None:
        if event["type"] == "text":
            delays.append(time.time() * 1000 - event["at"])

    await v.send(chat, STREAM_TURN)
    if via == "ws":
        async with v.socket(chat) as ws:
            async for event in ws_events(ws):
                note(event)
                if finished(event):
                    break
    else:
        async for event in v.sse(chat):
            note(event)
            if finished(event):
                break
    return delays


async def main() -> None:
    urls = runner_urls()
    print("| runner | new chat, first turn starts (median / p95) | same chat, next turn starts |")
    print("|---|---|---|")
    for name, base in urls.items():
        await reset_budget(base)
        cold, warm = await start_latency(base)
        print(f"| {name} | {summary(cold)} | {summary(warm)} |")
    print()
    print("| runner and transport | stored to received (median / p95) |")
    print("|---|---|")
    for name, base in urls.items():
        for via in ("sse", "ws") if name == "do" else ("sse",):
            await reset_budget(base)
            async with Visitor(base) as v:
                chat = await v.new_chat()
                print(f"| {name} over {via} | {summary(await delivery_latency(v, chat, via))} |")


if __name__ == "__main__":
    asyncio.run(main())
