"""The model client behind a small protocol, so the API can run against a scripted fake in tests
and against Claude in production.

- `StructuredModel.parse`: one small structured-output call (Claude Haiku 5.5 by default), e.g.
  "which of these USDA foods is 'Big Mac'?". Returns a validated Pydantic object or None.

Accounting: every API request is reported through `on_call` exactly once - success, error,
refusal or cancellation (from a `finally`, with the usage known so far) - so the caller can write
`llm_calls` immediately and the cost cap never under-counts. Any failure that means "no usable
answer" (connection, auth, rate limit after the SDK's retries, 5xx, timeout) raises
`LLMUnavailable`; a 400 `invalid_request_error` raises its subclass `LLMRejected`.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import anthropic
from pydantic import BaseModel, ValidationError

__all__ = [
    "HAIKU",
    "SONNET",
    "AnthropicStructuredModel",
    "CallSink",
    "CallStatus",
    "LLMRejected",
    "LLMUnavailable",
    "ModelCall",
    "StructuredModel",
    "Usage",
]

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"

type CallStatus = Literal["ok", "refusal", "max_tokens", "error", "cancelled"]
type CallSink = Callable[["ModelCall"], Awaitable[None]]
type Block = dict[str, Any]


class LLMUnavailable(Exception):
    """The model gave no usable answer (its request was already reported via on_call)."""


class LLMRejected(LLMUnavailable):
    """The API rejected the request itself (400 invalid_request_error)."""


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
            self.cache_creation_input_tokens + other.cache_creation_input_tokens,
        )


@dataclass(frozen=True, slots=True)
class ModelCall:
    """One API request, as logged to `llm_calls`. With a server-side refusal fallback one
    request can run on two models: `parts` then lists (model, usage) per attempt
    (from `usage.iterations`) and is what gets priced; otherwise `parts` is empty and
    (model, usage) is priced."""

    purpose: str  # "choose_food" | ...
    model: str  # the model that produced the returned message
    usage: Usage  # total over parts
    latency_ms: int
    status: CallStatus
    request_id: str | None = None
    error: str | None = None  # error text, or the refusal category
    parts: tuple[tuple[str, Usage], ...] = ()


class StructuredModel(Protocol):
    async def parse[T: BaseModel](
        self, *, purpose: str, system: str, prompt: str, schema: type[T], on_call: CallSink
    ) -> T | None:
        """`None` when the model refused or its output didn't validate (after one retry).
        Raises LLMUnavailable when the API can't be reached."""
        ...


class AnthropicStructuredModel:
    """`StructuredModel` on the Claude API via `client.messages.create` (not `.parse`, which
    raises inside the SDK and loses the usage): `output_config={"effort": effort, "format":
    {"type": "json_schema", "schema": anthropic.transform_schema(schema)}}`, `max_tokens=2048`
    (room for adaptive thinking), no `fallbacks` (Haiku has none). Report the call first, then:
    `refusal` -> None (no retry); `max_tokens` -> retry once with 4096; take the first `text`
    block (thinking blocks come first) and `schema.model_validate_json` it; a validation error
    -> retry once with the error appended; then None."""

    def __init__(self, client: Any, model: str = HAIKU, *, effort: str = "low") -> None:
        self.client = client
        self.model = model
        self.effort = effort

    async def parse[T: BaseModel](
        self, *, purpose: str, system: str, prompt: str, schema: type[T], on_call: CallSink
    ) -> T | None:
        output_format: Block = {"type": "json_schema", "schema": anthropic.transform_schema(schema)}
        text, max_tokens = prompt, 2_048
        cut = invalid = False
        while True:
            message = await self._create(purpose, system, text, max_tokens, output_format, on_call)
            if message.stop_reason == "refusal":
                return None
            if message.stop_reason == "max_tokens":
                if cut:
                    return None
                cut, max_tokens = True, 4_096
                continue
            answer = next((b.text for b in message.content if b.type == "text"), None)
            if answer is None:
                problem = "no answer"
            else:
                try:
                    return schema.model_validate_json(answer)
                except ValidationError as e:
                    problem = _brief(e)
            if invalid:
                return None
            invalid = True
            text = (
                f"{prompt}\n\nYour previous answer was rejected ({problem}). "
                "Answer again, following the schema exactly."
            )

    async def _create(
        self,
        purpose: str,
        system: str,
        text: str,
        max_tokens: int,
        output_format: Block,
        on_call: CallSink,
    ) -> Any:
        started = time.monotonic()
        message: Any = None
        status: CallStatus = "error"
        error: str | None = None
        request_id: str | None = None
        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": text}],
                output_config={"effort": self.effort, "format": output_format},
            )
            request_id = getattr(message, "_request_id", None)
            status, error = _outcome(message)
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except anthropic.BadRequestError as e:
            error, request_id = _describe(e), e.request_id
            raise LLMRejected(error) from e
        except anthropic.APIError as e:
            error, request_id = _describe(e), getattr(e, "request_id", None)
            raise LLMUnavailable(error) from e
        except Exception as e:
            error = _describe(e)
            raise
        finally:
            await on_call(
                _model_call(purpose, self.model, message, status, error, request_id, started)
            )
        return message


def _outcome(message: Any) -> tuple[CallStatus, str | None]:
    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        return "refusal", getattr(details, "category", None) or "refusal"
    if message.stop_reason == "max_tokens":
        return "max_tokens", None
    return "ok", None


def _model_call(
    purpose: str,
    requested: str,
    message: Any,
    status: CallStatus,
    error: str | None,
    request_id: str | None,
    started: float,
) -> ModelCall:
    latency_ms = int((time.monotonic() - started) * 1000)
    if message is None:
        return ModelCall(purpose, requested, Usage(), latency_ms, status, request_id, error)
    model = str(getattr(message, "model", None) or requested)
    usage = getattr(message, "usage", None)
    parts = _parts(usage, requested)
    total = sum((u for _, u in parts), Usage()) if parts else _usage(usage)
    return ModelCall(purpose, model, total, latency_ms, status, request_id, error, parts)


def _usage(usage: Any) -> Usage:
    """Token counts; fields the API leaves out or sends as null count as 0."""

    def get(name: str) -> int:
        return int(getattr(usage, name, None) or 0)

    return Usage(
        input_tokens=get("input_tokens"),
        output_tokens=get("output_tokens"),
        cache_read_input_tokens=get("cache_read_input_tokens"),
        cache_creation_input_tokens=get("cache_creation_input_tokens"),
    )


def _parts(usage: Any, requested: str) -> tuple[tuple[str, Usage], ...]:
    """Per-attempt (model, usage) when a request ran on more than one model (a refusal
    fallback); top-level usage covers only the attempt that produced the message."""
    iterations: list[Any] = list(getattr(usage, "iterations", None) or [])
    fell_back = any(getattr(it, "type", None) == "fallback_message" for it in iterations)
    if len(iterations) < 2 and not fell_back:
        return ()
    return tuple((str(getattr(it, "model", None) or requested), _usage(it)) for it in iterations)


def _describe(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"[:500]


def _brief(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(x) for x in e['loc']) or 'answer'}: {e['msg']}"
        for e in error.errors(include_url=False)[:5]
    )
