# SPDX-License-Identifier: AGPL-3.0-or-later
"""What each turn runner does when its Worker is killed mid-turn. A script, not a test: it needs to kill and
restart the Worker (tools/restart-host.sh) and the answer is a timeline, not a pass or a fail.

usage: uv run python -m tests.crash_probe do|queue|waituntil [attach] [quote]
  Starts a turn on a slow model, kills the Worker (SIGKILL) after three streamed pieces, starts it again on
  the same state, then follows the log for up to two minutes. With `attach` a WebSocket is opened after the
  restart (the object is instantiated, which is how a returning client meets it).
  With `quote` the turn buys airtime and the Worker is killed while the model words the answer that follows
  the quote: the resumed turn must end with the one quote it had made, one tool result and one card.
  PORT_BASE (default 8900) names the stack.
"""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .worker_client import Visitor, finished

ROOT = Path(__file__).resolve().parents[2]
BASE = int(os.environ.get("PORT_BASE", "8900"))
PORTS = {"do": BASE + 1, "queue": BASE + 3, "waituntil": BASE + 4}
WORDS = 100
AIRTIME = "airtime 500 to 07031234567 on mtn"


async def until_killable(v: Visitor, chat: str, quote: bool) -> str:
    """Reads the chat until the moment to kill the Worker; says what it saw."""
    seen = 0
    async with asyncio.timeout(30):
        async for event in v.sse(chat):
            if quote:
                seen += event["type"] == "tool"
                if seen and event["type"] == "text":
                    return "the quote made and the answer to it streaming"
            else:
                seen += event["type"] == "text"
                if seen >= 3:
                    return f"{seen} streamed pieces"
    raise AssertionError("the turn ended before there was a moment to kill the Worker")


async def main(runner: str, attach: bool, quote: bool = False) -> bool:
    base = f"http://localhost:{PORTS[runner]}"
    async with Visitor(base) as v:
        chat = await v.new_chat()
        await v.send(chat, AIRTIME if quote else f"slow:{WORDS}@0.1")
        print(f"{runner}: killing the Worker after {await until_killable(v, chat, quote)}")
        killed = time.monotonic()
        restart = subprocess.run(
            [ROOT / "tools/restart-host.sh", runner], capture_output=True, text=True, timeout=300, check=False
        )
        if restart.returncode != 0:
            print(f"{runner}: the Worker did not come back:\n{restart.stdout[-600:]}{restart.stderr[-600:]}")
            return False
        print(f"{runner}: back after {time.monotonic() - killed:.0f} s")
        if attach:
            async with v.socket(chat):
                return await follow(v, chat, killed, runner, quote)
        return await follow(v, chat, killed, runner, quote)


async def follow(v: Visitor, chat: str, killed: float, runner: str, quote: bool) -> bool:
    deadline = time.monotonic() + 120
    log: list = []
    while time.monotonic() < deadline:
        try:
            log = await v.log(chat)
        except httpx.HTTPError, OSError:
            log = []
        if any(finished(e) for e in log):
            break
        await asyncio.sleep(1)
    kinds = [e["type"] for e in log]
    done = next((e for e in log if finished(e)), None)
    text = "".join(e["payload"]["text"] for e in log if e["type"] == "assistant")
    complete = text.endswith("END") and text.count("word") == WORDS
    if quote:
        complete = (
            kinds.count("tool") == 1 and kinds.count("card") == 1 and text.endswith("Please check the card.")
        )
    print(f"{runner}: turn finished: {done is not None}, {time.monotonic() - killed:.0f} s after the kill")
    print(
        f"{runner}: events resumed={kinds.count('turn.resumed')} aborted={kinds.count('round.aborted')} "
        f"assistant={kinds.count('assistant')} tool={kinds.count('tool')} card={kinds.count('card')} "
        f"{'one_quote_and_its_answer' if quote else 'complete_text'}={complete}"
    )
    if done is None or not complete:
        notices = [e["payload"].get("text") for e in log if e["type"] == "notice"]
        replies = [e["payload"].get("text", "")[-60:] for e in log if e["type"] == "assistant"]
        print(f"{runner}: why: finished={done and done['payload']} notices={notices} replies={replies}")
    return done is not None and complete


if __name__ == "__main__":
    finished_and_whole = asyncio.run(
        asyncio.wait_for(main(sys.argv[1], "attach" in sys.argv[2:], "quote" in sys.argv[2:]), timeout=600)
    )
    sys.exit(0 if finished_and_whole or "--expect-finished" not in sys.argv else 1)
