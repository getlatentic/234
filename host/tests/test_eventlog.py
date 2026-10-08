# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from turns.db import UniqueViolation
from turns.eventlog import Draft, EventLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def log(chat, sql, clock):
    return EventLog(sql, chat.id, clock)


async def test_appends_take_consecutive_seqs_and_read_back_in_order(log):
    first = await log.append("user", {"text": "hi"})
    second = await log.append("text", {"message": "m", "text": "a"}, task="t1", ref="r")
    assert (first.seq, second.seq) == (1, 2)
    events = await log.read()
    assert [(e.seq, e.type, e.task, e.ref) for e in events] == [
        (1, "user", None, None),
        (2, "text", "t1", "r"),
    ]
    assert events[0].payload == {"text": "hi"}


async def test_read_after_a_cursor_returns_only_what_follows(log):
    for n in range(5):
        await log.append("user", {"text": str(n)})
    assert [e.seq for e in await log.read(after=3)] == [4, 5]
    assert await log.read(after=5) == []
    assert len(await log.read(limit=2)) == 2


async def test_context_leaves_out_streamed_text(log):
    await log.append("user", {"text": "hi"})
    await log.append("text", {"message": "m", "text": "a"})
    await log.append("assistant", {"message": "m", "text": "a"})
    assert [e.type for e in await log.context()] == ["user", "assistant"]


async def test_two_logs_of_one_chat_never_share_a_seq(chat, sql, clock):
    a, b = EventLog(sql, chat.id, clock), EventLog(sql, chat.id, clock)
    seqs = [(await w.append("user", {"text": "x"})).seq for w in (a, b, a, b)]
    assert seqs == [1, 2, 3, 4]


async def test_the_unique_key_refuses_a_duplicate_seq(chat, sql, clock):
    await EventLog(sql, chat.id, clock).append("user", {"text": "x"})
    with pytest.raises(UniqueViolation):
        await sql.execute(
            "INSERT INTO chat_event (chat_id, seq, type, task, ref, payload, created_at) "
            "VALUES (?, 1, 'user', '', '', '{}', 0)",
            chat.id,
        )


async def test_chats_have_separate_sequences(chat, other_chat, sql, clock):
    await EventLog(sql, chat.id, clock).append("user", {"text": "x"})
    assert (await EventLog(sql, other_chat.id, clock).append("user", {"text": "y"})).seq == 1


async def test_on_append_hears_every_event_after_it_is_stored(chat, sql, clock):
    heard = []

    async def hear(event):
        heard.append((event.seq, len(await log.read())))

    log = EventLog(sql, chat.id, clock, on_append=hear)
    await log.append("user", {"text": "x"})
    await log.append("user", {"text": "y"})
    assert heard == [(1, 1), (2, 2)]


async def test_last_seq_and_erase(log):
    assert await log.last_seq() == 0
    await log.append("user", {"text": "x"})
    assert await log.last_seq() == 1
    await log.erase()
    assert await log.read() == []


async def test_events_appended_together_take_consecutive_seqs_after_the_log_and_are_published_in_order(
    chat, sql, clock
):
    seen = []

    async def publish(event):
        seen.append((event.seq, event.type))

    log = EventLog(sql, chat.id, clock, on_append=publish)
    await log.append("user", {"text": "hi"})
    events = await log.append_all(
        [Draft("tool", {"n": 1}, "t1"), Draft("card", {"n": 2}, "t1", "qt-1"), Draft("notice", {"n": 3})]
    )
    assert [(e.seq, e.type, e.task, e.ref) for e in events] == [
        (2, "tool", "t1", None),
        (3, "card", "t1", "qt-1"),
        (4, "notice", None, None),
    ]
    assert seen == [(1, "user"), (2, "tool"), (3, "card"), (4, "notice")]
    stored = await log.read()
    assert [(e.seq, e.type, e.payload) for e in stored[1:]] == [
        (2, "tool", {"n": 1}),
        (3, "card", {"n": 2}),
        (4, "notice", {"n": 3}),
    ]


async def test_events_appended_together_are_all_in_the_log_or_none_is(chat, sql, clock):
    """One statement: when the database refuses the second row, the first is not left behind."""
    log = EventLog(sql, chat.id, clock)
    await log.append("user", {"text": "hi"})
    await sql.execute(
        "CREATE TRIGGER refuse_cards BEFORE INSERT ON chat_event WHEN NEW.type = 'card' "
        "BEGIN SELECT RAISE(ABORT, 'no cards today'); END"
    )
    with pytest.raises(Exception, match="no cards today"):
        await log.append_all([Draft("tool", {}), Draft("card", {}, ref="qt-1")])
    assert [e.type for e in await log.read()] == ["user"]
    await sql.execute("DROP TRIGGER refuse_cards")
    assert [e.seq for e in await log.append_all([Draft("tool", {})])] == [2]
