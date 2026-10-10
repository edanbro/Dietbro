"""Model clients behind two small protocols, so the agent loop and the API can run against a
scripted fake in tests and against Claude in production.

- `ChatModel.respond`: one streamed assistant response for the agent loop (Claude Sonnet 5.5 by
  default). Text deltas go to `on_text` as they arrive; the full content blocks come back
  unchanged so the transcript can be replayed append-only (thinking blocks included).
- `StructuredModel.parse`: one small structured-output call (Claude Haiku 5.5 by default), e.g.
  "which of these USDA foods is 'Big Mac'?". Returns a validated Pydantic object or None.

Both report a `ModelCall` per API request for cost accounting (`llm_calls`). Any failure that
means "no usable answer from the model" (connection, auth, rate limit after the SDK's retries,
5xx, unparseable output twice) raises `LLMUnavailable`; callers fall back to the offline path.
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
    "CallStatus",
    "ChatModel",
    "LLMUnavailable",
    "ModelCall",
    "StructuredModel",
    "TextSink",
    "Turn",
    "Usage",
]

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"

type CallStatus = Literal["ok", "refusal", "max_tokens", "error"]
type TextSink = Callable[[str], Awaitable[None]]
type Block = dict[str, Any]


class LLMUnavailable(Exception):
    """The model gave no usable answer; use the offline path. `call` is set when a request was
    made (so its tokens are still logged)."""

    def __init__(self, message: str, call: "ModelCall | None" = None) -> None:
        super().__init__(message)
        self.call = call


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
    """One API request, as logged to `llm_calls`."""

    purpose: str  # "chat" | "choose_food" | ...
    model: str  # the model that served it (response.model; may be a fallback model)
    usage: Usage
    latency_ms: int
    status: CallStatus
    request_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Turn:
    """One assistant response. `content` holds the API content blocks exactly as returned
    (`type`-tagged dicts, thinking signatures and fallback blocks included), ready to append to
    the transcript as `{"role": "assistant", "content": content}`."""

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
    ) -> Turn: ...


class StructuredModel(Protocol):
    async def parse[T: BaseModel](
        self, *, purpose: str, system: str, prompt: str, schema: type[T]
    ) -> tuple[T | None, list[ModelCall]]:
        """`None` when the model refused or its output didn't validate (after one retry).
        Every API request made is returned for logging, failed ones included."""
        ...


class AnthropicChatModel:
    """`ChatModel` on the Claude API (`anthropic.AsyncAnthropic`), streamed.

    Request shape (see docs/adr/0013-llm-layer.md):
    - `client.beta.messages.stream(...)` with `model`, `max_tokens=16000`, `system`, `tools`
      (strict, buffered input - no eager streaming: inputs are tiny and we want the server's
      schema guarantee), `messages`, `output_config={"effort": effort}` ("low" for chat).
    - Adaptive thinking (the only mode; display omitted) with
      `block_binding={"prefix_mismatch_behavior": "drop_block"}` under beta
      `thinking-binding-controls-2026-08-01`, so a system-prompt change between deploys drops
      old thinking blocks instead of failing replayed threads.
    - Server-side refusal fallback `fallbacks="default"` (beta `server-side-fallback-2026-07-01`)
      for models that support it (Sonnet 5.5 / Opus 5.5 / Fable 5.1), never for Haiku.
    - Top-level `cache_control={"type": "ephemeral"}` (automatic prompt caching); the system
      prompt and tool list are byte-stable, volatile context lives in the user turn.
    - Text deltas -> `on_text`; final message via the stream's final-message helper; content
      blocks serialised for replay; `stop_reason`, `usage`, served `model` and request id
      recorded. Typed SDK errors (RateLimitError, APIStatusError, APIConnectionError, ...) become
      `LLMUnavailable`.
    """

    def __init__(
        self,
        client: Any,  # anthropic.AsyncAnthropic
        model: str = SONNET,
        *,
        effort: str = "low",
        max_tokens: int = 16_000,
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
    ) -> Turn:
        raise NotImplementedError


class AnthropicStructuredModel:
    """`StructuredModel` on the Claude API: `client.messages.parse(..., output_format=schema)`
    (structured outputs), `output_config={"effort": effort}` ("low"), `max_tokens=2048` (room for
    adaptive thinking), no `fallbacks` (Haiku has none). A refusal or a validation failure is
    retried once with the error appended; then `(None, calls)`."""

    def __init__(self, client: Any, model: str = HAIKU, *, effort: str = "low") -> None:
        self.client = client
        self.model = model
        self.effort = effort

    async def parse[T: BaseModel](
        self, *, purpose: str, system: str, prompt: str, schema: type[T]
    ) -> tuple[T | None, list[ModelCall]]:
        raise NotImplementedError
