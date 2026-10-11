"""The Claude clients against recorded-shape API responses (no network): request bodies,
streaming, fallback stripping, per-attempt usage, error mapping and call reporting."""

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any, Literal

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, Field

from larder_llm.client import (
    HAIKU,
    SONNET,
    AnthropicChatModel,
    AnthropicStructuredModel,
    LLMRejected,
    LLMUnavailable,
    ModelCall,
    Usage,
    supports_fallback,
)
from larder_llm.pricing import call_cost_micro_usd, cost_micro_usd
from larder_llm.tools import api_tools

type Block = dict[str, Any]
type Handler = Callable[[httpx2.Request], httpx2.Response]

SYSTEM: list[Block] = [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}]
MESSAGES: list[Block] = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


class Wire:
    """A fake Messages API: answers each request with the next queued response."""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def client(self) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(
            api_key="test-key",
            base_url="http://claude.test",
            max_retries=0,
            http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(self)),
        )

    def body(self, i: int = 0) -> Block:
        return json.loads(self.requests[i].content)


def sse(*events: Block) -> httpx2.Response:
    text = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    return httpx2.Response(
        200,
        headers={"content-type": "text/event-stream", "request-id": "req_stream"},
        content=text.encode(),
    )


def start(model: str = SONNET, **usage: int | None) -> Block:
    base: dict[str, int | None] = {
        "input_tokens": 40,
        "output_tokens": 1,
        "cache_read_input_tokens": 3400,
        "cache_creation_input_tokens": None,
    }
    return {
        "type": "message_start",
        "message": {
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": base | usage,
        },
    }


def block(index: int, content: Block, *deltas: Block) -> list[Block]:
    return [
        {"type": "content_block_start", "index": index, "content_block": content},
        *({"type": "content_block_delta", "index": index, "delta": d} for d in deltas),
        {"type": "content_block_stop", "index": index},
    ]


def thinking(index: int, signature: str = "EqQBsig") -> list[Block]:
    return block(
        index,
        {"type": "thinking", "thinking": "", "signature": ""},
        {"type": "signature_delta", "signature": signature},
    )


def text(index: int, *pieces: str) -> list[Block]:
    return block(
        index, {"type": "text", "text": ""}, *({"type": "text_delta", "text": p} for p in pieces)
    )


def tool_use(index: int, tool_id: str, name: str, args: Block) -> list[Block]:
    return block(
        index,
        {"type": "tool_use", "id": tool_id, "name": name, "input": {}, "caller": None},
        {"type": "input_json_delta", "partial_json": json.dumps(args)},
    )


def end(stop_reason: str, output_tokens: int = 30, **extra: Any) -> list[Block]:
    delta: Block = {"stop_reason": stop_reason, "stop_sequence": None}
    if "stop_details" in extra:
        delta["stop_details"] = extra.pop("stop_details")
    return [
        {
            "type": "message_delta",
            "delta": delta,
            "usage": {"output_tokens": output_tokens, **extra},
        },
        {"type": "message_stop"},
    ]


class Sink:
    def __init__(self) -> None:
        self.log: list[tuple[str, Any]] = []
        self.calls: list[ModelCall] = []

    async def text(self, delta: str) -> None:
        self.log.append(("text", delta))

    async def reset(self) -> None:
        self.log.append(("reset", None))

    async def call(self, call: ModelCall) -> None:
        self.calls.append(call)


async def respond(model: AnthropicChatModel, sink: Sink) -> Any:
    return await model.respond(
        system=SYSTEM,
        tools=api_tools(),
        messages=MESSAGES,
        on_text=sink.text,
        on_reset=sink.reset,
        on_call=sink.call,
    )


def no_nones(node: Any, path: str = "") -> list[str]:
    if node is None:
        return [path]
    if isinstance(node, dict):
        return [p for k, v in node.items() for p in no_nones(v, f"{path}.{k}")]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    if isinstance(node, list):
        return [p for i, v in enumerate(node) for p in no_nones(v, f"{path}[{i}]")]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return []


# --- chat -------------------------------------------------------------------------------------


async def test_chat_request_shape_for_sonnet() -> None:
    wire = Wire(sse(start(), *thinking(0), *text(1, "Hi ", "there."), *end("end_turn")))
    sink = Sink()
    turn = await respond(AnthropicChatModel(wire.client()), sink)
    body = wire.body()
    assert body["model"] == SONNET
    assert body["max_tokens"] == 4096
    assert body["stream"] is True
    assert body["thinking"] == {
        "type": "adaptive",
        "block_binding": {"prefix_mismatch_behavior": "drop_block"},
    }
    assert body["output_config"] == {"effort": "low"}
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["fallbacks"] == "default"
    assert body["system"] == SYSTEM
    assert body["messages"] == MESSAGES
    assert body["tools"] == api_tools()
    assert all(t["strict"] is True and "eager_input_streaming" not in t for t in body["tools"])
    assert wire.requests[0].headers["anthropic-beta"] == (
        "thinking-binding-controls-2026-08-01,server-side-fallback-2026-07-01"
    )
    assert turn.stop_reason == "end_turn"
    assert turn.content == [
        {"type": "thinking", "thinking": "", "signature": "EqQBsig"},
        {"type": "text", "text": "Hi there."},
    ]
    assert sink.log == [("text", "Hi "), ("text", "there.")]
    assert sink.calls == [turn.call]
    assert turn.call.status == "ok"
    assert turn.call.request_id == "req_stream"
    assert turn.call.usage == Usage(40, 30, 3400, 0)  # a null cache field counts as 0
    assert turn.call.parts == ()


async def test_haiku_never_gets_fallbacks() -> None:
    wire = Wire(sse(start(HAIKU), *text(0, "ok"), *end("end_turn")))
    await respond(AnthropicChatModel(wire.client(), HAIKU, effort="medium"), Sink())
    body = wire.body()
    assert "fallbacks" not in body
    assert body["output_config"] == {"effort": "medium"}
    assert wire.requests[0].headers["anthropic-beta"] == "thinking-binding-controls-2026-08-01"


def test_fallback_support_by_model() -> None:
    assert supports_fallback("claude-sonnet-5-5")
    assert supports_fallback("claude-opus-5-5")
    assert supports_fallback("claude-fable-5-1")
    assert not supports_fallback("claude-haiku-5-5")
    assert not supports_fallback("claude-sonnet-5")


async def test_tool_use_blocks_serialise_for_replay() -> None:
    args = {"query": "spicy", "slot": "dinner"}
    wire = Wire(
        sse(
            start(),
            *thinking(0),
            *text(1, "Let me look."),
            *tool_use(2, "toolu_01", "search_recipes", args),
            *end("tool_use"),
        )
    )
    turn = await respond(AnthropicChatModel(wire.client()), Sink())
    assert turn.stop_reason == "tool_use"
    assert turn.content[2] == {
        "type": "tool_use",
        "id": "toolu_01",
        "name": "search_recipes",
        "input": args,
    }
    assert no_nones(turn.content) == []
    json.dumps(turn.content)  # plain JSON, ready to persist


async def test_a_mid_stream_fallback_is_stripped_and_priced_per_attempt() -> None:
    iterations = [
        {
            "type": "message",
            "model": SONNET,
            "input_tokens": 40,
            "output_tokens": 12,
            "cache_read_input_tokens": 3400,
            "cache_creation_input_tokens": 0,
        },
        {
            "type": "fallback_message",
            "model": "claude-sonnet-5",
            "input_tokens": 40,
            "output_tokens": 50,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 3400,
        },
    ]
    fallback_block = {
        "type": "fallback",
        "from": {"model": SONNET},
        "to": {"model": "claude-sonnet-5"},
        "trigger": {"type": "refusal", "category": None},
    }
    wire = Wire(
        sse(
            start(),
            *thinking(0, "declined-sig"),
            *text(1, "Sure, the exploit"),
            *tool_use(2, "toolu_declined", "get_plan", {}),
            *block(3, fallback_block),
            *thinking(4, "fallback-sig"),
            *text(5, "Here's your plan."),
            *end("end_turn", 50, iterations=iterations),
        )
    )
    sink = Sink()
    turn = await respond(AnthropicChatModel(wire.client()), sink)
    assert [b["type"] for b in turn.content] == ["text", "fallback", "thinking", "text"]
    assert turn.content[1] == {
        "type": "fallback",
        "from": {"model": SONNET},
        "to": {"model": "claude-sonnet-5"},
        "trigger": {"type": "refusal"},
    }
    assert turn.content[2]["signature"] == "fallback-sig"
    assert no_nones(turn.content) == []
    assert "from_" not in json.dumps(turn.content)
    assert sink.log == [
        ("text", "Sure, the exploit"),
        ("reset", None),
        ("text", "Here's your plan."),
    ]
    call = turn.call
    assert call.model == "claude-sonnet-5"
    assert call.parts == (
        (SONNET, Usage(40, 12, 3400, 0)),
        ("claude-sonnet-5", Usage(40, 50, 0, 3400)),
    )
    assert call.usage == Usage(80, 62, 3400, 3400)
    expected = cost_micro_usd(SONNET, Usage(40, 12, 3400, 0)) + cost_micro_usd(
        "claude-sonnet-5", Usage(40, 50, 0, 3400)
    )
    assert call_cost_micro_usd(call) == expected


async def test_a_refusal_reports_its_category() -> None:
    details = {"type": "refusal", "category": "cyber", "explanation": None}
    wire = Wire(sse(start(), *text(0, "I"), *end("refusal", 5, stop_details=details)))
    turn = await respond(AnthropicChatModel(wire.client()), Sink())
    assert turn.stop_reason == "refusal"
    assert turn.call.status == "refusal"
    assert turn.call.error == "cyber"


async def test_max_tokens_status() -> None:
    wire = Wire(sse(start(), *text(0, "Your plan"), *end("max_tokens", 4096)))
    turn = await respond(AnthropicChatModel(wire.client()), Sink())
    assert turn.call.status == "max_tokens"
    assert turn.call.usage.output_tokens == 4096


def api_error(status: int, kind: str) -> httpx2.Response:
    body = {"type": "error", "error": {"type": kind, "message": f"{kind} happened"}}
    return httpx2.Response(status, headers={"request-id": f"req_{status}"}, json=body)


@pytest.mark.parametrize(
    ("answer", "error", "request_id"),
    [
        (api_error(400, "invalid_request_error"), LLMRejected, "req_400"),
        (api_error(429, "rate_limit_error"), LLMUnavailable, "req_429"),
        (api_error(529, "overloaded_error"), LLMUnavailable, "req_529"),
        (api_error(401, "authentication_error"), LLMUnavailable, "req_401"),
        (httpx2.ConnectError("refused"), LLMUnavailable, None),
        (httpx2.ReadTimeout("slow"), LLMUnavailable, None),
    ],
)
async def test_errors_are_mapped_and_reported(
    answer: httpx2.Response | Exception, error: type[Exception], request_id: str | None
) -> None:
    wire = Wire(answer)
    sink = Sink()
    with pytest.raises(error) as raised:
        await respond(AnthropicChatModel(wire.client()), sink)
    assert error is LLMRejected or not isinstance(raised.value, LLMRejected)
    (call,) = sink.calls
    assert call.status == "error"
    assert call.request_id == request_id
    assert call.usage == Usage()
    assert call.error


async def test_an_error_mid_stream_reports_the_usage_so_far() -> None:
    overloaded = {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
    events = [start(), *text(0, "Hel")]
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    body += f"event: error\ndata: {json.dumps(overloaded)}\n\n"
    wire = Wire(
        httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())
    )
    sink = Sink()
    with pytest.raises(LLMUnavailable):
        await respond(AnthropicChatModel(wire.client()), sink)
    (call,) = sink.calls
    assert call.status == "error"
    assert call.usage == Usage(40, 1, 3400, 0)
    assert sink.log == [("text", "Hel")]


async def test_cancellation_is_reported() -> None:
    wire = Wire(sse(start(), *text(0, "Hello", " there"), *end("end_turn")))
    sink = Sink()

    async def cancel_on_text(delta: str) -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await AnthropicChatModel(wire.client()).respond(
            system=SYSTEM,
            tools=[],
            messages=MESSAGES,
            on_text=cancel_on_text,
            on_reset=sink.reset,
            on_call=sink.call,
        )
    (call,) = sink.calls
    assert call.status == "cancelled"
    assert call.usage.input_tokens == 40


async def test_a_deadline_bounds_the_request() -> None:
    wire = Wire(sse(start(), *text(0, "ok"), *end("end_turn")))
    model = AnthropicChatModel(wire.client(), deadline=time.monotonic() + 20)
    await respond(model, Sink())
    timeout = wire.requests[0].extensions["timeout"]
    assert 0 < timeout["read"] <= 20
    assert timeout["connect"] == 5.0

    late = AnthropicChatModel(wire.client(), deadline=time.monotonic() - 1)
    sink = Sink()
    with pytest.raises(LLMUnavailable):
        await respond(late, sink)
    assert sink.calls == []  # no request was made
    assert len(wire.requests) == 1


# --- structured -------------------------------------------------------------------------------


class Pick(BaseModel):
    fdc_id: int = Field(ge=1)
    confidence: Literal["high", "low"]


def message(stop_reason: str, *content: Block, model: str = HAIKU) -> httpx2.Response:
    body = {
        "id": "msg_02",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": list(content),
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 300,
            "output_tokens": 40,
            "cache_read_input_tokens": None,
            "cache_creation_input_tokens": None,
        },
    }
    return httpx2.Response(200, headers={"request-id": "req_json"}, json=body)


THINK: Block = {"type": "thinking", "thinking": "", "signature": "sig"}


def answer(data: Block) -> Block:
    return {"type": "text", "text": json.dumps(data)}


async def parse(wire: Wire, sink: Sink) -> Pick | None:
    return await AnthropicStructuredModel(wire.client()).parse(
        purpose="choose_food", system="Pick one.", prompt="Big Mac?", schema=Pick, on_call=sink.call
    )


async def test_structured_request_and_answer() -> None:
    wire = Wire(message("end_turn", THINK, answer({"fdc_id": 170720, "confidence": "high"})))
    sink = Sink()
    assert await parse(wire, sink) == Pick(fdc_id=170720, confidence="high")
    body = wire.body()
    assert body["model"] == HAIKU
    assert body["max_tokens"] == 2048
    assert body["system"] == "Pick one."
    assert body["messages"] == [{"role": "user", "content": "Big Mac?"}]
    assert body["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": anthropic.transform_schema(Pick)},
    }
    assert "fallbacks" not in body
    assert "stream" not in body
    assert "anthropic-beta" not in wire.requests[0].headers
    (call,) = sink.calls
    assert call == ModelCall(
        "choose_food", HAIKU, Usage(300, 40), call.latency_ms, "ok", "req_json"
    )


async def test_structured_refusal_is_none_without_retry() -> None:
    wire = Wire(message("refusal", answer({"fdc_id": 1})))
    sink = Sink()
    assert await parse(wire, sink) is None
    assert [c.status for c in sink.calls] == ["refusal"]


async def test_structured_max_tokens_retries_once_with_more_room() -> None:
    wire = Wire(
        message("max_tokens", THINK),
        message("end_turn", THINK, answer({"fdc_id": 5, "confidence": "low"})),
    )
    sink = Sink()
    assert await parse(wire, sink) == Pick(fdc_id=5, confidence="low")
    assert [wire.body(i)["max_tokens"] for i in range(2)] == [2048, 4096]
    assert [c.status for c in sink.calls] == ["max_tokens", "ok"]

    wire = Wire(message("max_tokens", THINK), message("max_tokens", THINK))
    assert await parse(wire, Sink()) is None


async def test_structured_invalid_output_retries_once_with_the_error() -> None:
    wire = Wire(
        message("end_turn", answer({"fdc_id": 0, "confidence": "high"})),
        message("end_turn", answer({"fdc_id": 9, "confidence": "high"})),
    )
    sink = Sink()
    assert await parse(wire, sink) == Pick(fdc_id=9, confidence="high")
    retry = wire.body(1)["messages"][0]["content"]
    assert retry.startswith("Big Mac?\n\nYour previous answer was rejected (fdc_id: ")
    assert len(sink.calls) == 2

    wire = Wire(message("end_turn", answer({"x": 1})), message("end_turn", THINK))
    assert await parse(wire, Sink()) is None
    assert len(wire.requests) == 2


async def test_structured_errors() -> None:
    sink = Sink()
    with pytest.raises(LLMUnavailable):
        await parse(Wire(api_error(500, "api_error")), sink)
    assert [c.status for c in sink.calls] == ["error"]
    with pytest.raises(LLMRejected):
        await parse(Wire(api_error(400, "invalid_request_error")), Sink())
