# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio

import pytest

from turns import kinds
from turns.alternatives import drive as drive_module
from turns.alternatives.drive import drive
from turns.alternatives.lease import LEASE_MS, Lease, LeaseLost

from .support import ScriptedModel
from .test_chat_core import Core


async def test_one_holder_at_a_time_and_a_dead_holders_lease_expires(chat, sql, clock):
    first, second = Lease(sql, chat.id, clock), Lease(sql, chat.id, clock)
    assert await first.claim() is True
    assert await second.claim() is False
    assert await first.claim() is True
    clock.advance(LEASE_MS / 1000 + 1)
    assert await second.claim() is True
    with pytest.raises(LeaseLost):
        await first.renew()


async def test_a_released_lease_can_be_taken_at_once(chat, sql, clock):
    first, second = Lease(sql, chat.id, clock), Lease(sql, chat.id, clock)
    await first.claim()
    await first.release()
    assert await second.claim() is True


async def test_a_lease_is_renewed_by_its_holder(chat, sql, clock):
    lease = Lease(sql, chat.id, clock)
    await lease.claim()
    clock.advance(LEASE_MS / 1000 - 1)
    await lease.renew()
    clock.advance(LEASE_MS / 1000 - 1)
    assert await Lease(sql, chat.id, clock).claim() is False


@pytest.fixture
def core(chat, sql, clock):
    def make(model):
        return Core(chat, sql, clock, model)

    return make


async def test_the_turn_runs_once_when_two_runners_start_together(core):
    model = ScriptedModel("only once")
    c = core(model)
    await c.core.log.append(kinds.USER, {"text": "hi"})
    await asyncio.gather(drive(c.core), drive(c.core))
    assert len(model.sent) == 1
    assert (await c.types()).count("turn.finished") == 1


async def test_a_message_that_arrives_after_a_turn_is_run_by_the_next_drive(core):
    model = ScriptedModel("one", "two")
    c = core(model)
    await c.core.log.append(kinds.USER, {"text": "a"})
    await drive(c.core)
    await c.core.log.append(kinds.USER, {"text": "b"})
    await drive(c.core)
    assert len(model.sent) == 2


async def test_a_runner_that_loses_its_lease_is_stopped(core, monkeypatch):
    monkeypatch.setattr(drive_module, "HEARTBEAT_SECONDS", 0.01)
    gate = asyncio.Event()

    class Held(ScriptedModel):
        async def stream(self, messages, tools):
            await gate.wait()
            async for piece in super().stream(messages, tools):
                yield piece

    c = core(Held("never finished"))
    await c.core.log.append(kinds.USER, {"text": "hi"})
    task = asyncio.ensure_future(drive(c.core))
    await asyncio.sleep(0.05)
    await c.core.database.execute(
        "UPDATE chat_lease SET holder = 'someone else' WHERE chat_id = ?", c.core.chat_id
    )
    await asyncio.wait_for(task, 2)
    gate.set()
    assert "assistant" not in await c.types()
