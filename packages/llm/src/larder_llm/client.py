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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel

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
]

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"

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
    ) -> None:
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.purpose = purpose

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
        raise NotImplementedError


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
        raise NotImplementedError
