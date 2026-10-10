"""The agent loop: one chat turn = model responses and tool calls until the model answers.

    history + user turn -> respond -> [tool_use -> validate -> handler -> tool_result]* -> text

Rules (docs/adr/0013-llm-layer.md):
- Append-only. Each assistant response is appended as returned (`Turn.content`), then ONE user
  message with all its tool results, in tool_use order (no text blocks in it). Nothing earlier
  is ever edited, so thinking blocks stay valid and the prompt cache keeps hitting.
- Tools of one response run sequentially, in block order (a write builds on the plan version
  the previous write saved). Write tools are limited per turn (`write_limits`, e.g.
  request_replan 2, create_recipe 3); calls over the limit get `is_error` ("put all changes in
  one request_replan").
- Inputs are validated with the tool's Pydantic model before the handler runs. An invalid input
  or unknown tool name (exact, else unambiguous case-insensitive match) gets `is_error: true`
  with the validation message; a second invalid input in the turn stops with `stop="invalid"`.
  A handler that raises gets `is_error` "internal error" (logged) and the loop continues.
- stop_reason: `tool_use` -> run the tools; `end_turn` -> done; `max_tokens` -> done (if the
  response holds a tool_use, it is not run); `refusal` -> stop; `pause_turn` (no server tools,
  so unexpected) -> stop. At most `max_rounds` responses.
- Never raises for model failures: LLMUnavailable -> `stop="unavailable"` (LLMRejected ->
  `stop="rejected"`), returning the rounds completed so far. Deadline exceeded (the caller
  cancels via a cancel scope) is the caller's business.
- Transcript invariant, enforced before returning (`close_transcript`): the returned messages
  never end with an unanswered tool_use - a final assistant response whose tool_use blocks were
  not run is DROPPED (max_tokens / refusal / pause_turn / unavailable mid-response), while
  responses whose tools ran keep their tool_result message; a turn that stops after a
  tool-result message (max_rounds, invalid, unavailable on the next response) ends there. A
  refused response is never kept. `check_transcript(messages)` validates role alternation
  (user first), tool_use <-> tool_result id pairing in the very next message, and that every
  thinking block has a signature; the service runs it before persisting.
- `text` is what the user saw, minus text discarded by `on_reset` (fallback) and minus the
  text of dropped responses (the service tells the client to reset in that case).
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from larder_llm.client import ChatModel, ModelCall
from larder_llm.tools import ToolDef

__all__ = [
    "AgentEvents",
    "AgentResult",
    "Handler",
    "ToolOutcome",
    "check_transcript",
    "run_agent",
]

type Block = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """A handler's answer: `content` is what the model reads (JSON text, kept compact)."""

    content: str
    is_error: bool = False


type Handler = Callable[[BaseModel], Awaitable[ToolOutcome]]


class AgentEvents(Protocol):
    """Progress hooks for the SSE stream and accounting."""

    async def text(self, delta: str) -> None: ...
    async def reset(self) -> None: ...  # discard text streamed in the current response
    async def tool_started(self, name: str, tool_input: BaseModel) -> None: ...
    async def tool_finished(self, name: str, outcome: ToolOutcome) -> None: ...
    async def call(self, call: ModelCall) -> None: ...  # every API request, immediately


@dataclass(slots=True)
class AgentResult:
    messages: list[Block]  # API messages appended this turn (assistant + tool-result users)
    text: str  # everything shown to the user this turn (all streamed text, in order)
    calls: list[ModelCall] = field(default_factory=list[ModelCall])
    stop: Literal[
        "done", "max_rounds", "refusal", "max_tokens", "invalid", "unavailable", "rejected"
    ] = "done"
    tools_used: list[str] = field(default_factory=list[str])
    writes: int = 0  # write-tool calls that ran (whatever their outcome)


async def run_agent(
    model: ChatModel,
    *,
    system: list[Block],
    tools: Sequence[ToolDef],
    history: Sequence[Block],
    user_message: Block,
    handlers: Mapping[str, Handler],
    events: AgentEvents,
    max_rounds: int = 6,
    write_limits: Mapping[str, int] | None = None,
) -> AgentResult:
    """Run one turn. `history` (earlier turns) and `user_message` are not mutated; the returned
    `messages` are what to persist after `user_message`."""
    raise NotImplementedError


def check_transcript(messages: Sequence[Block]) -> list[str]:
    """Problems that would make the API reject a replay of `messages` ([] = fine)."""
    raise NotImplementedError
