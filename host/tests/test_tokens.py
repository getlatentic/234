# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from turns import kinds, tokens
from turns.eventlog import Event


def test_four_characters_make_a_token_and_a_partial_token_counts():
    assert tokens.text_tokens("") == 0
    assert tokens.text_tokens("abcd") == 1
    assert tokens.text_tokens("abcde") == 2


def test_a_message_costs_its_text_its_calls_and_a_small_overhead():
    plain = {"role": "user", "content": "x" * 40}
    assert tokens.message_tokens(plain) == tokens.MESSAGE_OVERHEAD + 10
    calling = {"role": "assistant", "content": None, "tool_calls": [{"id": "c", "function": {"name": "f"}}]}
    assert tokens.message_tokens(calling) > tokens.MESSAGE_OVERHEAD


def test_a_request_adds_the_tool_definitions_it_carries():
    messages = [{"role": "user", "content": "x" * 40}]
    tools = [{"type": "function", "function": {"name": "a" * 100}}]
    assert tokens.request_tokens(messages, tools) > tokens.request_tokens(messages, [])
    assert tokens.request_tokens(messages, []) == tokens.message_tokens(messages[0])


def reply(seq, **payload):
    return Event(seq, kinds.ASSISTANT, None, None, {"message": "m", "text": "hi", **payload}, 0)


@pytest.mark.parametrize(
    ("events", "ratio"),
    [
        ([], 1.0),
        ([reply(1)], 1.0),
        ([reply(1, estimate=1000)], 1.0),
        ([reply(1, estimate=1000, usage={"prompt_tokens": 1500})], 1.5),
        ([reply(1, estimate=1000, usage={"prompt_tokens": 100})], tokens.LEAST_RATIO),
        ([reply(1, estimate=1000, usage={"prompt_tokens": 9000})], tokens.MOST_RATIO),
        (
            [
                reply(1, estimate=1000, usage={"prompt_tokens": 1500}),
                reply(2, estimate=2000, usage={"prompt_tokens": 2200}),
                reply(3),
            ],
            1.1,
        ),
    ],
    ids=["none", "no data", "no usage", "measured", "floor", "ceiling", "the latest pair wins"],
)
def test_the_latest_count_from_the_provider_corrects_the_estimate(events, ratio):
    assert tokens.ratio_of(events) == pytest.approx(ratio)


def test_a_correction_scales_the_estimate():
    assert tokens.corrected(1000, 1.25) == 1250
