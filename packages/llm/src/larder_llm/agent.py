"""The agent loop: one chat turn = model responses and tool calls until the model answers.

    history + user turn -> respond -> [tool_use -> validate -> handler -> tool_result]* -> text

Rules (docs/adr/0013-llm-layer.md):
- The transcript is append-only. Each assistant response is appended exactly as returned
  (`Turn.content`), then one user message with *all* its tool results (parallel calls share one
  message). Nothing earlier is ever edited, so thinking blocks stay valid and the prompt cache
  keeps hitting.
- Tool inputs are validated with the tool's Pydantic model before the handler runs. An invalid
  input (or an unknown tool) is answered with `is_error: true` and the validation message, so
  the model can correct it once; a second invalid input in the same turn stops the loop with
  `stop="invalid"` and the caller takes the offline path ("retry once with the error, then fall
  back to the deterministic path", PLAN §7).
- `stop_reason`: `tool_use` -> run tools (unless the response was cut off: `max_tokens` with a
  tool_use present never runs it); `end_turn` -> done; `refusal` -> stop, run nothing;
  `pause_turn` -> append and continue; `max_tokens` without tools -> done with what was said.
- At most `max_rounds` model responses per turn; then stop with `stop="max_rounds"`.
- `LLMUnavailable` from the model propagates (the caller decides between the offline path and an
  error event, depending on whether text was already streamed).
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from larder_llm.client import ChatModel, ModelCall
from larder_llm.tools import ToolDef

__all__ = ["AgentEvents", "AgentResult", "Handler", "ToolOutcome", "run_agent"]

type Block = dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """A handler's answer: `content` is what the model reads (JSON text, kept compact)."""

    content: str
    is_error: bool = False


type Handler = Callable[[BaseModel], Awaitable[ToolOutcome]]


class AgentEvents(Protocol):
    """Progress hooks for the SSE stream."""

    async def text(self, delta: str) -> None: ...
    async def tool_started(self, name: str, tool_input: BaseModel) -> None: ...
    async def tool_finished(self, name: str, outcome: ToolOutcome) -> None: ...


@dataclass(slots=True)
class AgentResult:
    messages: list[Block]  # API messages appended this turn (assistant + tool-result users)
    text: str  # everything shown to the user this turn (all streamed text, in order)
    calls: list[ModelCall] = field(default_factory=list[ModelCall])
    stop: Literal["done", "max_rounds", "refusal", "max_tokens", "invalid"] = "done"
    tools_used: list[str] = field(default_factory=list[str])


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
) -> AgentResult:
    """Run one turn. `history` (earlier turns) and `user_message` are not mutated; the returned
    `messages` are what to persist after `user_message`."""
    raise NotImplementedError
