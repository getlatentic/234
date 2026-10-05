# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a kill in the middle of a compaction leaves: a script, not a test, since it kills and restarts the
Worker (tools/restart-host.sh) and its answer is a timeline.

usage: CONTEXT_WINDOW_TOKENS=8000 COMPACT_AT=0.75 KEEP_RECENT_TOKENS=500 [PORT_BASE=8900] \
  uv run python -u -m tests.crash_probe_compaction [--expect-finished]
  (the stack must have been started with the same three values: the restart reads them from this environment)

It talks in a chat until the context is over the threshold, with the scripted summariser held back (a slow
stream), so the compaction is in progress for a good while. It kills the Worker while the summary is being
written, starts the Worker again, reads the log the kill left (the watchdog may already have written its
resumption after it), and follows the log until the turn
that was being answered has finished. It reports whether
  - the log the kill left has no compaction in it, no gap, and nothing half written;
  - the watchdog resumed the turn, which compacted the chat once and answered;
  - the final log is gapless and holds the same number of compactions as the context needed.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .long_chat import LongChat, talk
from .worker_client import FAKE_MODEL, Visitor, finished, reset_budget

ROOT = Path(__file__).resolve().parents[2]
BASE = int(os.environ.get("PORT_BASE", "8900"))
SLOW = 0.4
NEEDED = ("CONTEXT_WINDOW_TOKENS", "COMPACT_AT", "KEEP_RECENT_TOKENS")


async def summary_started(http: httpx.AsyncClient, asked_before: int) -> bool:
    requests = (await http.get(f"{FAKE_MODEL}/v1/_requests")).json()
    return sum("<conversation>" in str(r["messages"]) for r in requests) > asked_before


async def talk_until_a_summary_is_being_written(v: Visitor, chat: LongChat, http: httpx.AsyncClient) -> int:
    """Sends messages until the summariser has been asked; returns the seq of the message that made it so."""
    for n in range(60):
        answer = await v.send(chat.chat, talk(n))
        while answer.status_code == 429:
            await asyncio.sleep(3)
            answer = await v.send(chat.chat, talk(n))
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if await summary_started(http, 0):
                return answer.json()["seq"]
            if any(
                e["type"] == "turn.finished"
                for e in await v.log(chat.chat)
                if e["seq"] > answer.json()["seq"]
            ):
                break
            await asyncio.sleep(0.3)
    raise AssertionError("the chat never grew past the threshold")


def restart() -> float:
    started = time.monotonic()
    done = subprocess.run(
        [ROOT / "tools/restart-host.sh", "do"], capture_output=True, text=True, timeout=300, check=False
    )
    if done.returncode != 0:
        raise SystemExit(f"the Worker did not come back:\n{done.stdout[-600:]}{done.stderr[-600:]}")
    return time.monotonic() - started


async def main() -> bool:
    missing = [name for name in NEEDED if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"set {', '.join(missing)} to the values the stack was started with")
    await reset_budget(f"http://localhost:{BASE + 1}")
    async with httpx.AsyncClient() as http, Visitor(f"http://localhost:{BASE + 1}") as v:
        await http.get(f"{FAKE_MODEL}/v1/_reset")
        await http.post(f"{FAKE_MODEL}/v1/_config", json={"word_delay": 0, "summary_delay": SLOW})
        async with LongChat.open(v) as chat:
            trigger = await talk_until_a_summary_is_being_written(v, chat, http)
            before = [e for e in await v.log(chat.chat)]
            print(f"a summary is being written for the message at seq {trigger}; killing the Worker")
            killed = time.monotonic()
            # The summariser is fast again before the Worker is back: its watchdog resumes the turn at once.
            await http.post(f"{FAKE_MODEL}/v1/_config", json={"summary_delay": 0})
            print(f"back after {restart():.0f} s")
            # The host is the Worker, so the log is read once it is back, when its watchdog may already have
            # resumed the turn: what the kill left is the log up to the snapshot, and what follows is the
            # resumption.
            read = await v.log(chat.chat)
            left, since = read[: len(before)], read[len(before) :]
            gapless = [e["seq"] for e in left] == list(range(1, len(left) + 1))
            made = sum(e["type"] == "compaction" for e in left)
            print(f"the log the kill left: {len(left)} events, {made} compactions, gapless {gapless}")
            assert left == before, "the kill changed the log it left"
            assert not since or since[0]["type"] == "turn.resumed", f"written since the kill: {since[:1]}"
            deadline = time.monotonic() + 150
            log = left
            while time.monotonic() < deadline:
                try:
                    log = await v.log(chat.chat)
                except httpx.HTTPError, OSError:
                    log = left
                if any(finished(e) and e["seq"] > trigger for e in log):
                    break
                await asyncio.sleep(1)
    return report(log, left, trigger, time.monotonic() - killed)


def report(log: list[dict], left: list[dict], trigger: int, after: float) -> bool:
    done = any(finished(e) and e["seq"] > trigger for e in log)
    kinds = [e["type"] for e in log]
    new = [e for e in log[len(left) :] if e["type"] == "compaction"]
    gapless = [e["seq"] for e in log] == list(range(1, len(log) + 1))
    whole = all(
        e["payload"]["covers"]["last"] < e["seq"] and e["payload"]["summary"].startswith("## ") for e in new
    )
    answered = any(e["type"] == "assistant" and e["seq"] > trigger for e in log)
    print(
        f"turn finished: {done}, {after:.0f} s after the kill; compactions written after it: {len(new)}; "
        f"resumed={kinds.count('turn.resumed')} aborted={kinds.count('round.aborted')} gapless={gapless} "
        f"compaction_whole={whole} answered={answered}"
    )
    return done and len(new) == 1 and gapless and whole and answered and kinds.count("turn.resumed") >= 1


if __name__ == "__main__":
    ok = asyncio.run(asyncio.wait_for(main(), timeout=900))
    sys.exit(0 if ok or "--expect-finished" not in sys.argv else 1)
