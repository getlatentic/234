# SPDX-License-Identifier: AGPL-3.0-or-later
import json

import httpx
import pytest

from turns.model import ContextTooLong, Finished, ModelError, OpenAICompatible, TextDelta
from turns.settings import Settings

CONFIG = {"mcp_url": "http://x", "llm_base_url": "http://m/v1", "llm_api_key": "k", "llm_model": "gpt-oss"}


def sse(*chunks: str) -> httpx.Response:
    body = "".join(f"data: {c}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


def model(handler, **changes) -> OpenAICompatible:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatible(Settings(**{**CONFIG, **changes}), client)


async def collect(m, messages=(), tools=()):
    return [piece async for piece in m.stream(list(messages), list(tools))]


async def test_text_and_tool_call_pieces_are_assembled_and_the_finish_reason_kept():
    seen = {}

    def handler(request):
        seen["body"], seen["auth"] = json.loads(request.content), request.headers["authorization"]
        return sse(
            '{"choices":[{"delta":{"content":"Hi "}}]}',
            '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"s__t","arguments":"{\\"a\\""}}]}}]}',
            '{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":":1}"}}]},"finish_reason":"tool_calls"}]}',
        )

    pieces = await collect(model(handler), [{"role": "user", "content": "x"}], [{"type": "function"}])
    assert pieces[0] == TextDelta("Hi ")
    assert pieces[-1] == Finished("tool_calls", [{"id": "c1", "name": "s__t", "arguments": '{"a":1}'}])
    assert seen["auth"] == "Bearer k"
    body = seen["body"]
    assert body["stream"] is True and body["tool_choice"] == "auto" and body["reasoning_effort"] == "low"
    assert "max_tokens" not in body and "max_completion_tokens" not in body


async def test_a_request_without_tools_names_no_tool_choice_and_reasoning_can_be_off():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return sse('{"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}')

    await collect(model(handler, reasoning_effort="off"))
    assert "tools" not in seen["body"] and "tool_choice" not in seen["body"]
    assert "reasoning_effort" not in seen["body"]


async def test_a_reply_that_ran_out_of_room_says_so():
    pieces = await collect(model(lambda r: sse('{"choices":[{"delta":{},"finish_reason":"length"}]}')))
    assert pieces == [Finished("length", [])]


async def test_a_claude_model_and_a_missing_key_are_refused():
    with pytest.raises(ModelError, match="Claude"):
        await collect(model(lambda r: sse(), llm_model="us.anthropic.claude-x"))
    with pytest.raises(ModelError, match="No model"):
        await collect(model(lambda r: sse(), llm_api_key=""))


async def test_an_http_error_is_a_plain_message_that_names_no_url():
    with pytest.raises(ModelError) as failure:
        await collect(model(lambda request: httpx.Response(500)))
    assert "500" in str(failure.value) and "http://" not in str(failure.value)


async def test_a_dropped_connection_is_a_plain_message():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ModelError, match="could not be reached"):
        await collect(model(handler))


async def test_the_usage_chunk_with_no_choices_is_read_and_returned_with_the_reply():
    pieces = await collect(
        model(
            lambda r: sse(
                '{"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}',
                '{"choices":[],"usage":{"prompt_tokens":1234,"completion_tokens":7,"total_tokens":1241}}',
            )
        )
    )
    assert pieces == [TextDelta("hi"), Finished("stop", [], {"prompt_tokens": 1234, "completion_tokens": 7})]


async def test_the_request_asks_for_usage_unless_it_is_switched_off():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return sse('{"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}')

    await collect(model(handler))
    await collect(model(handler, stream_usage=False))
    assert seen[0]["stream_options"] == {"include_usage": True} and "stream_options" not in seen[1]


@pytest.mark.parametrize(
    ("status", "body", "too_long"),
    [
        (400, '{"error":{"message":"This model\'s maximum context length is 131072 tokens"}}', True),
        (400, '{"error":{"code":"context_length_exceeded"}}', True),
        (400, '{"message":"Input is too long for requested model"}', True),
        (413, "request entity too large: too many tokens", True),
        (400, '{"error":{"message":"Invalid tool schema"}}', False),
        (500, '{"message":"the prompt is too long"}', False),
        (429, "slow down", False),
    ],
)
async def test_a_refusal_because_the_context_did_not_fit_is_told_from_any_other(status, body, too_long):
    with pytest.raises(ModelError) as failure:
        await collect(model(lambda request: httpx.Response(status, text=body)))
    assert isinstance(failure.value, ContextTooLong) is too_long
    assert str(failure.value) == f"The model endpoint answered HTTP {status}."


async def test_an_error_event_in_a_stream_that_began_with_200_is_an_error_not_an_empty_reply():
    """The Bedrock endpoint answers 200 and then sends the refusal as an event."""
    event = '{"error":{"code":"validation_error","message":"The maximum context length is 262144 tokens."}}'
    with pytest.raises(ContextTooLong, match="reported an error") as failure:
        await collect(model(lambda request: sse(event)))
    assert "262144" not in str(failure.value)
    other = '{"error":{"code":"throttled","message":"Too many requests"}}'
    with pytest.raises(ModelError, match="reported an error") as failure:
        await collect(model(lambda request: sse(other)))
    assert not isinstance(failure.value, ContextTooLong)


@pytest.mark.parametrize(
    ("status", "transient"),
    [
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
        (520, True),
        (530, True),
        (400, False),
        (401, False),
        (404, False),
    ],
)
async def test_a_busy_endpoint_is_transient_and_a_refused_request_is_not(status, transient):
    with pytest.raises(ModelError) as failure:
        await collect(model(lambda request: httpx.Response(status)))
    assert failure.value.transient is transient


async def test_a_dropped_connection_is_transient_and_a_context_refusal_and_a_missing_key_are_not():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ModelError) as dropped:
        await collect(model(handler))
    assert dropped.value.transient is True
    with pytest.raises(ContextTooLong) as too_long:
        await collect(model(lambda r: httpx.Response(400, text="maximum context length is 131072 tokens")))
    assert too_long.value.transient is False
    with pytest.raises(ModelError) as unset:
        await collect(model(lambda r: sse(), llm_api_key=""))
    assert unset.value.transient is False


async def test_a_throttling_error_in_a_stream_that_began_with_200_is_transient():
    error = '{"error": {"message": "Too many requests, please slow down: throttling"}}'
    with pytest.raises(ModelError) as failure:
        await collect(model(lambda r: sse(f"{error}")))
    assert failure.value.transient is True
