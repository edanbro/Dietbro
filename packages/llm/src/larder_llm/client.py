"""Model clients behind two small protocols, so the agent loop and the API can run against a
scripted fake in tests and against Claude in production.

- `ChatModel.respond`: one streamed assistant response for the agent loop (Claude Sonnet 5.5 by
  default). Text deltas go to `on_text` as they arrive; the content blocks come back in wire
  form so the transcript can be replayed append-only (thinking blocks included).
- `StructuredModel.parse`: one small structured-output call (Claude Haiku 5.5 by default), e.g.
  "which of these USDA foods is 'Big Mac'?". Returns a validated Pydantic object or None.

Accounting: every API request is reported through `on_call` exactly once - success, error,
refusal or cancellation (from a `finally`, with the usage known so far) - so the caller can write
`llm_calls` immediately and the cost cap never under-counts. Any failure that means "no usable
answer" (connection, auth, rate limit after the SDK's retries, 5xx, timeout) raises
`LLMUnavailable`; a 400 `invalid_request_error` raises its subclass `LLMRejected` (usually a bad
replayed transcript: the caller starts a fresh transcript epoch and retries once).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

import anthropic
from pydantic import BaseModel, ValidationError

__all__ = [
    "HAIKU",
    "SONNET",
    "AnthropicChatModel",
    "AnthropicStructuredModel",
    "CallSink",
    "CallStatus",
    "ChatModel",
    "LLMRejected",
    "LLMUnavailable",
    "ModelCall",
    "ResetSink",
    "StructuredModel",
    "TextSink",
    "Turn",
    "Usage",
    "supports_fallback",
]

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"

THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models with a server-side refusal fallback ("default" routing). Haiku has none.
FALLBACK_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1")

type CallStatus = Literal["ok", "refusal", "max_tokens", "error", "cancelled"]
type TextSink = Callable[[str], Awaitable[None]]
type ResetSink = Callable[[], Awaitable[None]]  # discard the text streamed so far this response
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

    purpose: str  # "chat" | "choose_food" | ...
    model: str  # the model that produced the returned message
    usage: Usage  # total over parts
    latency_ms: int
    status: CallStatus
    request_id: str | None = None
    error: str | None = None  # error text, or the refusal category
    parts: tuple[tuple[str, Usage], ...] = ()


@dataclass(frozen=True, slots=True)
class Turn:
    """One assistant response. `content` holds the content blocks in wire form
    (`block.to_dict()`: aliases like `from`, no unset/None fields), ready to append to the
    transcript as `{"role": "assistant", "content": content}`. Thinking blocks are kept even
    when their text is empty (the signature matters). After a server-side refusal fallback,
    the declined attempt's thinking / redacted_thinking / tool_use blocks before the last
    `fallback` block are removed (they must not be replayed or executed)."""

    content: list[Block]
    stop_reason: str | None  # end_turn | tool_use | max_tokens | refusal | pause_turn | ...
    call: ModelCall


class ChatModel(Protocol):
    async def respond(
        self,
        *,
        system: list[Block],
        tools: list[Block],
        messages: list[Block],
        on_text: TextSink,
        on_reset: ResetSink,
        on_call: CallSink,
    ) -> Turn:
        """`on_reset` fires when a fallback block arrives mid-stream: text streamed before it
        belonged to a declined attempt and must be discarded by the client."""
        ...


class StructuredModel(Protocol):
    async def parse[T: BaseModel](
        self, *, purpose: str, system: str, prompt: str, schema: type[T], on_call: CallSink
    ) -> T | None:
        """`None` when the model refused or its output didn't validate (after one retry).
        Raises LLMUnavailable when the API can't be reached."""
        ...


class AnthropicChatModel:
    """`ChatModel` on the Claude API (`anthropic.AsyncAnthropic`), streamed.

    Request shape (see docs/adr/0013-llm-layer.md):
    - `client.beta.messages.stream(...)` with `model`, `max_tokens=4096` (replies are short;
      bounds a turn's worst-case cost), `system` (the caller puts `cache_control` on its last
      block so tools+system are cached once for every user), `tools` (strict, buffered input -
      no eager streaming: inputs are tiny and we want the server's schema guarantee),
      `messages`, `output_config={"effort": effort}` ("low" for chat).
    - Adaptive thinking (the only mode; display omitted) with
      `block_binding={"prefix_mismatch_behavior": "drop_block"}` under beta
      `thinking-binding-controls-2026-08-01`, so a system-prompt change between deploys drops
      old thinking blocks instead of failing replayed threads.
    - Server-side refusal fallback `fallbacks="default"` (beta `server-side-fallback-2026-07-01`)
      for models that support it (Sonnet 5.5 / Opus 5.5 / Fable 5.1), never for Haiku.
      A `fallback` block mid-stream -> `on_reset()`; content stripped as described in Turn;
      usage priced per `usage.iterations` entry (ModelCall.parts).
    - Top-level `cache_control={"type": "ephemeral"}` as well (automatic caching of the
      conversation tail); volatile context lives in the user turn.
    - Per-request `client.with_options(timeout=Timeout(remaining, connect=5), max_retries=1)`
      when the caller passes a deadline (turn budget).
    - Text deltas -> `on_text`; final message via the stream's final-message helper; usage
      fields that are None count as 0. `on_call` fires once in `finally`: on an exception or
      cancellation, usage comes from the stream's current snapshot if any (status error /
      cancelled). `stop_reason == "refusal"` -> status refusal, `stop_details.category` in
      `error`. BadRequestError -> LLMRejected; other typed SDK errors (RateLimitError,
      APIStatusError, APIConnectionError, APITimeoutError) -> LLMUnavailable.
    """

    def __init__(
        self,
        client: Any,  # anthropic.AsyncAnthropic
        model: str = SONNET,
        *,
        effort: str = "low",
        max_tokens: int = 4_096,
        purpose: str = "chat",
        deadline: float | None = None,  # time.monotonic() by which the turn must end
    ) -> None:
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.purpose = purpose
        self.deadline = deadline

    async def respond(
        self,
        *,
        system: list[Block],
        tools: list[Block],
        messages: list[Block],
        on_text: TextSink,
        on_reset: ResetSink,
        on_call: CallSink,
    ) -> Turn:
        client = _with_deadline(self.client, self.deadline)
        started = time.monotonic()
        stream: Any = None
        message: Any = None
        status: CallStatus = "error"
        error: str | None = None
        request_id: str | None = None
        try:
            async with client.beta.messages.stream(**self.params(system, tools, messages)) as s:
                stream = s
                request_id = s.request_id
                async for event in s:
                    if event.type == "text":
                        await on_text(event.text)
                    elif event.type == "content_block_start" and (
                        event.content_block.type == "fallback"
                    ):
                        await on_reset()
                message = await s.get_final_message()
            status, error = _outcome(message)
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except anthropic.BadRequestError as e:
            error, request_id = _describe(e), e.request_id or request_id
            raise LLMRejected(error) from e
        except anthropic.APIError as e:
            error = _describe(e)
            request_id = getattr(e, "request_id", None) or request_id
            raise LLMUnavailable(error) from e
        except Exception as e:
            error = _describe(e)
            raise
        finally:
            final = message if message is not None else _snapshot(stream)
            call = _model_call(self.purpose, self.model, final, status, error, request_id, started)
            await on_call(call)
        done = cast(Any, message)  # only reached when the stream completed
        return Turn(_wire_content(done.content), done.stop_reason, call)

    def params(self, system: list[Block], tools: list[Block], messages: list[Block]) -> Block:
        """Keyword arguments for `client.beta.messages.stream`."""
        params: Block = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "tools": tools,
            "messages": messages,
            "thinking": {
                "type": "adaptive",
                "block_binding": {"prefix_mismatch_behavior": "drop_block"},
            },
            "output_config": {"effort": self.effort},
            "cache_control": {"type": "ephemeral"},
            "betas": [THINKING_BINDING_BETA],
        }
        if supports_fallback(self.model):
            params["fallbacks"] = "default"
            params["betas"] = [THINKING_BINDING_BETA, FALLBACK_BETA]
        return params


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


def supports_fallback(model: str) -> bool:
    return any(model == m or model.startswith(f"{m}-") for m in FALLBACK_MODELS)


def _with_deadline(client: Any, deadline: float | None) -> Any:
    """Bound the request (and its single retry) by what's left of the turn."""
    if deadline is None:
        return client
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LLMUnavailable("the turn's deadline has passed")
    timeout = anthropic.Timeout(remaining, connect=min(5.0, remaining))
    return client.with_options(timeout=timeout, max_retries=1)


def _outcome(message: Any) -> tuple[CallStatus, str | None]:
    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        return "refusal", getattr(details, "category", None) or "refusal"
    if message.stop_reason == "max_tokens":
        return "max_tokens", None
    return "ok", None


def _snapshot(stream: Any) -> Any:
    """The message accumulated so far (usage from message_start / the last message_delta)."""
    if stream is None:
        return None
    try:
        return stream.current_message_snapshot
    except AssertionError:  # nothing received yet
        return None


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


def _wire_content(blocks: list[Any]) -> list[Block]:
    """Content blocks as they must be replayed: `to_dict()` (API names such as `from`, unset
    fields left out) without null fields. After a server-side fallback, the declined attempt's
    blocks other than text that come before the last `fallback` block are dropped: they must
    not be replayed or executed."""
    wire = [_drop_none(cast(Block, b.to_dict(mode="json")), b.type == "tool_use") for b in blocks]
    last = max((i for i, b in enumerate(wire) if b.get("type") == "fallback"), default=None)
    if last is None:
        return wire
    return [b for i, b in enumerate(wire) if i >= last or b.get("type") == "text"]


def _drop_none(data: Block, keep_input: bool) -> Block:
    """None-valued fields removed, recursively - but never inside a tool's `input`, which is
    replayed exactly as the model wrote it."""
    out: Block = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict) and not (keep_input and key == "input"):
            value = _drop_none(cast(Block, value), False)
        out[key] = value
    return out


def _describe(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"[:500]


def _brief(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(x) for x in e['loc']) or 'answer'}: {e['msg']}"
        for e in error.errors(include_url=False)[:5]
    )
