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
  text of dropped responses (the service tells the client to reset in that case). Responses'
  texts are joined with a blank line. A client clears all reply text on a reset, so after
  `events.reset()` the loop re-sends the text kept from earlier responses as one `text` event:
  the client then shows exactly `text`.
"""

import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ValidationError

from larder_llm.client import ChatModel, LLMRejected, LLMUnavailable, ModelCall
from larder_llm.tools import ToolDef, api_tools, by_name

__all__ = [
    "AgentEvents",
    "AgentResult",
    "Handler",
    "ToolOutcome",
    "check_transcript",
    "close_transcript",
    "run_agent",
]

type Block = dict[str, Any]
type Stop = Literal[
    "done", "max_rounds", "refusal", "max_tokens", "invalid", "unavailable", "rejected"
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """A handler's answer: `content` is what the model reads (JSON text, kept compact)."""

    content: str
    is_error: bool = False


type Handler = Callable[[BaseModel], Awaitable[ToolOutcome]]


class AgentEvents(Protocol):
    """Progress hooks for the SSE stream and accounting."""

    async def text(self, delta: str) -> None: ...
    async def reset(self) -> None: ...  # discard the reply text shown so far (see `text`)
    async def tool_started(self, name: str, tool_input: BaseModel) -> None: ...
    async def tool_finished(self, name: str, outcome: ToolOutcome) -> None: ...
    async def call(self, call: ModelCall) -> None: ...  # every API request, immediately


@dataclass(slots=True)
class AgentResult:
    messages: list[Block]  # API messages appended this turn (assistant + tool-result users)
    text: str  # everything shown to the user this turn (all streamed text, in order)
    calls: list[ModelCall] = field(default_factory=list[ModelCall])
    stop: Stop = "done"
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
    result = AgentResult(messages=[], text="")
    runner = _Tools(list(tools), handlers, events, dict(write_limits or {}), result)
    wire_tools = api_tools(runner.defs)
    base = [*history, user_message]

    async def on_call(call: ModelCall) -> None:
        result.calls.append(call)
        await events.call(call)

    for round_no in range(1, max_rounds + 1):
        stream = _Stream(events, result.text)
        try:
            turn = await model.respond(
                system=system,
                tools=wire_tools,
                messages=[*base, *result.messages],
                on_text=stream.text,
                on_reset=stream.reset,
                on_call=on_call,
            )
        except LLMRejected:
            await stream.reset()
            result.stop = "rejected"
            break
        except LLMUnavailable:
            await stream.reset()
            result.stop = "unavailable"
            break
        uses = [b for b in turn.content if b.get("type") == "tool_use"]
        if turn.stop_reason == "tool_use" and uses:
            result.messages.append({"role": "assistant", "content": turn.content})
            result.text += stream.current
            answers = await runner.run(uses)
            result.messages.append({"role": "user", "content": answers})
            if runner.invalid >= 2:
                result.stop = "invalid"
                break
            if round_no == max_rounds:
                result.stop = "max_rounds"
            continue
        result.stop = _final_stop(turn.stop_reason)
        keep = result.stop in ("done", "max_tokens") and not uses and _replayable(turn.content)
        if keep:
            result.messages.append({"role": "assistant", "content": turn.content})
            result.text += stream.current
        else:
            await stream.reset()
        break
    result.messages = close_transcript(result.messages)
    return result


def _final_stop(stop_reason: str | None) -> Stop:
    if stop_reason == "refusal":
        return "refusal"
    if stop_reason == "max_tokens":
        return "max_tokens"
    if stop_reason == "pause_turn":  # only server tools pause, and we have none
        return "unavailable"
    return "done"


def _replayable(content: list[Block]) -> bool:
    """Non-empty, and every thinking block complete (a cut-off one has no signature)."""
    return bool(content) and all(
        (b.get("type") != "thinking" or b.get("signature"))
        and (b.get("type") != "redacted_thinking" or b.get("data"))
        for b in content
    )


class _Stream:
    """Text of the response in progress, on top of the text kept from earlier responses."""

    def __init__(self, events: AgentEvents, kept: str) -> None:
        self.events = events
        self.kept = kept
        self.current = ""

    async def text(self, delta: str) -> None:
        if not delta:
            return
        if not self.current and self.kept and not self.kept.endswith("\n"):
            delta = "\n\n" + delta
        self.current += delta
        await self.events.text(delta)

    async def reset(self) -> None:
        """Discard this response's text (fallback, or the response is dropped)."""
        if not self.current:
            return
        self.current = ""
        await self.events.reset()
        if self.kept:
            await self.events.text(self.kept)


class _Tools:
    """Runs one response's tool calls in order and answers each of them."""

    def __init__(
        self,
        defs: list[ToolDef],
        handlers: Mapping[str, Handler],
        events: AgentEvents,
        limits: dict[str, int],
        result: AgentResult,
    ) -> None:
        self.defs = defs
        self.handlers = handlers
        self.events = events
        self.limits = limits
        self.result = result
        self.used: Counter[str] = Counter()
        self.invalid = 0

    async def run(self, uses: list[Block]) -> list[Block]:
        answers: list[Block] = []
        for block in uses:
            if self.invalid >= 2:  # the turn ends: don't act on a confused response
                answers.append(_answer(block, ToolOutcome("Not run: the turn ended.", True)))
            else:
                answers.append(_answer(block, await self._one(block)))
        return answers

    async def _one(self, block: Block) -> ToolOutcome:
        name = str(block.get("name", ""))
        tool = by_name(name, self.defs)
        if tool is None:
            self.invalid += 1
            known = ", ".join(d.name for d in self.defs)
            return ToolOutcome(f"Unknown tool {name!r}. The tools are: {known}.", True)
        limit = self.limits.get(tool.name)
        if limit is not None and self.used[tool.name] >= limit:
            hint = (
                " Put all changes in one request_replan." if tool.name == "request_replan" else ""
            )
            return ToolOutcome(f"Not run: at most {limit} {tool.name} per message.{hint}", True)
        try:
            tool_input = tool.input_model.model_validate(block.get("input", {}))
        except ValidationError as e:
            self.invalid += 1
            return ToolOutcome(f"Invalid input for {tool.name}: {_brief(e)}", True)
        handler = self.handlers.get(tool.name)
        if handler is None:
            logger.error("no handler for tool %s", tool.name)
            return ToolOutcome("internal error", True)
        self.used[tool.name] += 1
        self.result.tools_used.append(tool.name)
        if tool.writes:
            self.result.writes += 1
        await self.events.tool_started(tool.name, tool_input)
        try:
            outcome = await handler(tool_input)
        except Exception:
            logger.exception("tool %s failed", tool.name)
            outcome = ToolOutcome("internal error", True)
        await self.events.tool_finished(tool.name, outcome)
        return outcome


def _answer(block: Block, outcome: ToolOutcome) -> Block:
    answer: Block = {
        "type": "tool_result",
        "tool_use_id": block.get("id"),
        "content": outcome.content,
    }
    if outcome.is_error:
        answer["is_error"] = True
    return answer


def _brief(error: ValidationError) -> str:
    """The validation errors, short enough for the model to act on."""
    parts = [
        f"{'.'.join(str(x) for x in e['loc']) or 'input'}: {e['msg']}"
        for e in error.errors(include_url=False)[:5]
    ]
    return "; ".join(parts)


def close_transcript(messages: list[Block]) -> list[Block]:
    """Never end on an unanswered tool call: drop a final assistant response whose tool_use
    blocks were not run (dropping from the end edits nothing earlier)."""
    out = list(messages)
    if out and out[-1].get("role") == "assistant" and _tool_ids(out[-1]):
        out.pop()
    return out


def check_transcript(messages: Sequence[Block]) -> list[str]:
    """Problems that would make the API reject a replay of `messages` ([] = fine).

    User first; no two assistant messages in a row (consecutive user messages are allowed:
    the API merges them, and a turn that ended after tool results is followed by the next
    turn's user message); non-empty content; every tool_use id unique and answered by a
    tool_result in the very next message, tool results first in their message and only for
    the previous message's calls; every thinking block signed."""
    problems: list[str] = []
    seen: set[str] = set()
    for i, msg in enumerate(messages):
        role = msg.get("role")
        blocks = _blocks(msg)
        prev = messages[i - 1] if i else None
        if role not in ("user", "assistant"):
            problems.append(f"message {i}: unexpected role {role!r}")
            continue
        if i == 0 and role != "user":
            problems.append("message 0: the transcript must start with a user message")
        if not blocks:
            problems.append(f"message {i}: empty content")
            continue
        if role == "assistant":
            if prev is not None and prev.get("role") == "assistant":
                problems.append(f"message {i}: two assistant messages in a row")
            problems += _check_assistant(i, blocks, seen)
            ids = _tool_ids(msg)
            if ids:
                nxt = messages[i + 1] if i + 1 < len(messages) else None
                answered = _result_ids(nxt) if nxt is not None and nxt.get("role") == "user" else []
                missing = [x for x in ids if x not in answered]
                if missing:
                    problems.append(f"message {i}: tool_use without a tool_result next: {missing}")
        else:
            problems += _check_results(i, blocks, prev)
    return problems


def _blocks(msg: Block) -> list[Block]:
    content = msg.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]  # pyright: ignore[reportUnknownVariableType]
    return []


def _tool_ids(msg: Block) -> list[str]:
    return [str(b.get("id")) for b in _blocks(msg) if b.get("type") == "tool_use"]


def _result_ids(msg: Block) -> list[str]:
    return [str(b.get("tool_use_id")) for b in _blocks(msg) if b.get("type") == "tool_result"]


def _check_assistant(i: int, blocks: list[Block], seen: set[str]) -> list[str]:
    problems: list[str] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "thinking" and not block.get("signature"):
            problems.append(f"message {i}: thinking block without a signature")
        elif kind == "redacted_thinking" and not block.get("data"):
            problems.append(f"message {i}: redacted_thinking block without data")
        elif kind == "tool_use":
            tool_id = str(block.get("id") or "")
            if not tool_id or tool_id in seen:
                problems.append(f"message {i}: missing or repeated tool_use id {tool_id!r}")
            seen.add(tool_id)
    return problems


def _check_results(i: int, blocks: list[Block], prev: Block | None) -> list[str]:
    kinds = [b.get("type") for b in blocks]
    if "tool_result" not in kinds:
        return []
    problems: list[str] = []
    first_other = next((n for n, k in enumerate(kinds) if k != "tool_result"), len(kinds))
    if "tool_result" in kinds[first_other:]:
        problems.append(f"message {i}: tool_result blocks must come first")
    calls = _tool_ids(prev) if prev is not None and prev.get("role") == "assistant" else []
    for answered in _result_ids({"content": blocks}):
        if answered not in calls:
            problems.append(f"message {i}: tool_result for {answered!r} answers no tool_use")
    return problems
