"""The structured Claude client against recorded-shape API responses (no network): request
body, retries, error mapping and call reporting."""

import json
from typing import Any, Literal

import anthropic
import httpx2
import pytest
from pydantic import BaseModel, Field

from larder_llm.client import (
    HAIKU,
    AnthropicStructuredModel,
    LLMRejected,
    LLMUnavailable,
    ModelCall,
    Usage,
)

type Block = dict[str, Any]


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


class Sink:
    def __init__(self) -> None:
        self.calls: list[ModelCall] = []

    async def call(self, call: ModelCall) -> None:
        self.calls.append(call)


def api_error(status: int, kind: str) -> httpx2.Response:
    body = {"type": "error", "error": {"type": kind, "message": f"{kind} happened"}}
    return httpx2.Response(status, headers={"request-id": f"req_{status}"}, json=body)


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


@pytest.mark.parametrize(
    ("reply", "error", "request_id"),
    [
        (api_error(429, "rate_limit_error"), LLMUnavailable, "req_429"),
        (api_error(529, "overloaded_error"), LLMUnavailable, "req_529"),
        (api_error(401, "authentication_error"), LLMUnavailable, "req_401"),
        (httpx2.ConnectError("refused"), LLMUnavailable, None),
    ],
)
async def test_structured_errors_are_mapped_and_reported(
    reply: httpx2.Response | Exception, error: type[Exception], request_id: str | None
) -> None:
    sink = Sink()
    with pytest.raises(error):
        await parse(Wire(reply), sink)
    (call,) = sink.calls
    assert (call.status, call.request_id) == ("error", request_id)
