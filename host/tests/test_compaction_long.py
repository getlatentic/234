# SPDX-License-Identifier: AGPL-3.0-or-later
"""A long chat, in Pidgin and English, with quotes in every state: the context the model is sent stays under
the threshold, every amount, number and quote survives two or more compactions, the quote still waiting
for the person stays in front of the model, and a question after the compactions is answered from what is
left."""

import json
import re

import pytest

from turns import fold, kinds, messages, tokens
from turns.compaction import facts
from turns.hub import ToolOutcome

from . import scripted_recall
from .compaction_support import Rig, RoutedModel
from .log_builder import quote_view
from .support import FakeHub

PHONES = ("07031234567", "08051234567", "09012345678")
STATES = ("succeeded", "declined", "succeeded", "expired", "succeeded", "failed")
SMALL_TALK = (
    "How far? Abeg remind me wetin you fit do for me, I no sabi all these things well well",
    "Good morning, I hope the network dey work today. My brother said his own dey slow o",
    "Oga no wahala, I go check am later. Just tell me if you fit do airtime for another network too",
    "Thanks, that was quick. Abeg how much be the cheapest data plan wey dey for MTN this week?",
    "I dey fine, thank you. Please keep it short, I dey on the bus and the signal no too strong",
    "Can you explain the steps again? I am not sure I followed what the card asked me to do",
    "Alright. One of my customers said she would pay back tomorrow, I will remind her by message",
    "No problem at all, take your time. I am just checking a few things before I continue",
)


def amount_of(k: int) -> int:
    return 5000 + 150 * k


def expected(k: int) -> str:
    return f"₦{amount_of(k):,}"


class QuoteHub(FakeHub):
    """Makes a quote of the amount asked for, with an id of its own."""

    def __init__(self) -> None:
        super().__init__()
        self.made: list[tuple[str, int]] = []

    async def model_tools(self):
        return [{"type": "function", "function": {"name": "airtime__create_airtime_quote", "parameters": {}}}]

    async def call_model_tool(self, qualified, arguments, owner, key, account=False):
        ref = f"qt-{len(self.made):020x}"
        kobo = arguments["amount_kobo"]
        self.made.append((ref, kobo))
        result = quote_view(ref, "awaiting_approval", kobo, f"MTN airtime to {arguments['phone']}")
        result["content"] = [
            {"type": "text", "text": f"Quote {ref}: ₦{kobo // 100:,}.00 for MTN airtime. It awaits approval."}
        ]
        return ToolOutcome("airtime", "create_airtime_quote", result, "ui://airtime/card.html")


class Conversationalist:
    """The model of this chat: it makes quotes, chats, and answers from the messages it is sent, like one that
    reads its context carefully and nothing else."""

    def __init__(self) -> None:
        self.sent: list[list[dict]] = []
        self.turn = 0

    async def stream(self, sent, tools):
        from turns.model import Finished, TextDelta

        self.sent.append(sent)
        last = sent[-1]
        if last["role"] == "tool":
            yield TextDelta("Please check the card. ")
            yield Finished("stop", [])
            return
        text = last["content"]
        if match := re.search(r"buy ₦([\d,]+) MTN airtime for (\d{11})", text):
            call = {"id": f"call-{len(self.sent)}", "name": "airtime__create_airtime_quote",
                    "arguments": json.dumps(
                {"amount_kobo": int(match[1].replace(",", "")) * 100, "phone": match[2]}
            )}  # fmt: skip
            yield Finished("tool_calls", [call])
            return
        yield TextDelta(self.answer(sent, text) + " ")
        yield Finished("stop", [])

    def answer(self, sent, text):
        if recalled := scripted_recall.answer(sent):
            return recalled
        self.turn += 1
        return "Noted." if self.turn % 2 else "No wahala."


def _lines(sent):
    return [m["content"] or "" for m in sent if isinstance(m.get("content"), str)]


async def settle(r: Rig, hub: QuoteHub, states: dict[str, str]) -> None:
    """What the person does with the newest card, as the page and the card would leave it in the log."""
    events = await r.log.context()
    card = [e for e in events if e.type == kinds.CARD][-1]
    ref = card.ref
    k = int(ref.removeprefix("qt-"), 16)
    phase = states[ref]
    kobo = dict(hub.made)[ref]
    if phase != "awaiting_approval":
        await r.log.append(kinds.CARD_STATE, {"result": quote_view(ref, phase, kobo, "MTN airtime")}, ref=ref)
        note = f"The person's card for quote {ref} (₦{kobo // 100:,}.00) now shows: {phase}. "
        await r.log.append(kinds.CARD_CONTEXT, {"text": note})
    assert k == len(hub.made) - 1


def script() -> list[str]:
    turns, k = [], 0
    for n in range(150):
        if n % 10 == 9:
            turns.append(f"abeg buy ₦{amount_of(k):,} MTN airtime for {PHONES[k % 3]}")
            k += 1
        elif n in (20, 75):
            turns.append("Send 5k to Ada Okafor, GTBank 0123456789 when you are ready")
        else:
            turns.append(SMALL_TALK[n % len(SMALL_TALK)] + f" (message {n})")
    return turns


@pytest.fixture
def chat_rig(chat, sql, clock):
    hub, model = QuoteHub(), RoutedModel(Conversationalist())
    return Rig(chat, sql, clock, model, hub, context_window_tokens=4000, keep_recent_tokens=500), hub


QUOTES = 15


async def play(r: Rig, hub: QuoteHub, turns: list[str]) -> tuple[dict[str, str], list[int]]:
    """Sends each message, and settles each quote the way the person would: the last of them is left open."""
    states: dict[str, str] = {}
    sizes: list[int] = []
    for said in turns:
        await r.say(said)
        sizes.append(tokens.request_tokens(r.model.sent[-1], await hub.model_tools()))
        if said.startswith("abeg buy"):
            k = len(hub.made)
            states[hub.made[-1][0]] = "awaiting_approval" if k == QUOTES else STATES[(k - 1) % len(STATES)]
            await settle(r, hub, states)
    return states, sizes


async def test_a_long_mixed_chat_stays_under_the_threshold_and_keeps_what_matters(chat_rig):
    r, hub = chat_rig
    states, sizes = await play(r, hub, script())
    assert max(sizes) <= r.settings.compact_threshold_tokens
    compactions = await r.compactions()
    assert len(compactions) >= 3 and all(c.payload["trigger"] == "auto" for c in compactions)
    events = await r.events()

    for compaction in compactions:
        covered = [e for e in events if e.seq <= compaction.payload["covers"]["last"]]
        kept = facts.facts_of_events([e for e in events if e.seq > compaction.payload["covers"]["last"]])
        assert not facts.missing_from(compaction.payload["summary"], facts.facts_of_events(covered), kept)

    everything = "\n".join(_lines(messages.render(events, "sys")))
    needed = facts.facts_of_events(events)
    assert len(needed.amounts) >= QUOTES and needed.accounts == {"0123456789"} and needed.phones
    assert not facts.missing_from(everything, needed, facts.Facts())

    (open_ref,) = [ref for ref, phase in states.items() if phase == "awaiting_approval"]
    assert open_ref in everything and fold.card_phases(events)[open_ref] == "awaiting_approval"
    assert any(e.type == kinds.CARD and e.ref == open_ref for e in events)


async def test_a_question_after_the_compactions_is_answered_from_what_is_left(chat_rig):
    r, hub = chat_rig
    quiet = [SMALL_TALK[n % len(SMALL_TALK)] + f" (more {n})" for n in range(30)]
    states, _ = await play(r, hub, script()[:120] + quiet)
    assert len(await r.compactions()) >= 2
    paid = [k for k, (ref, _) in enumerate(hub.made) if states[ref] == "succeeded"]
    await r.say("what was the last amount I paid?")
    reply = [e for e in await r.events() if e.type == kinds.ASSISTANT][-1].payload["text"]
    assert expected(paid[-1]) in reply
    sent = r.model.sent[-1]
    assert sent[1]["content"].startswith(messages.SUMMARY_LABEL) and expected(paid[-1]) in sent[1]["content"]
    assert not any(expected(paid[-1]) in (m["content"] or "") for m in sent[2:])
