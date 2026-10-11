"""Scripted stand-ins for the model clients, for tests and offline demos. No network.

    chat = ScriptedChatModel([
        tool("search_recipes", {"query": "spicy", "slot": "dinner"}),
        tool("request_replan", {"changes": [...]}),
        say("Done - Thursday is now a chilli."),
    ])

Each scripted step is one assistant response. A step may also be a callable that receives the
messages sent so far and returns a response, so a test can react to tool results.

- Every response with content starts with a `think()` block (empty text, a unique signature),
  as Claude's do with display omitted, so thinking round-trips through persistence.
- Tool ids are unique across the process; text streams in chunks that join back to exactly
  the scripted text.
- `fail(after_text=...)` streams text, then raises LLMUnavailable; `reject()` raises
  LLMRejected; `refuse()` stops with `refusal`; `fallback(declined_text, then=step)` streams
  the declined text, calls on_reset, then answers `step` with a `fallback` block in the content
  and a two-part ModelCall.
- `strict=True` (default): every respond() asserts the transcript rules - user first, roles
  in order, every tool_use answered by matching tool_results in the next message, signed
  thinking, the last message a user message, system and tools unchanged, and each request's
  messages starting with the previous request's (append-only) - so transcript bugs that would
  400 in production fail in CI.
"""

import copy
import itertools
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import BaseModel

from larder_llm.agent import check_transcript
from larder_llm.client import (
    CallSink,
    CallStatus,
    LLMRejected,
    LLMUnavailable,
    ModelCall,
    ResetSink,
    TextSink,
    Turn,
    Usage,
)

__all__ = [
    "Script",
    "ScriptedChatModel",
    "ScriptedStructuredModel",
    "Step",
    "fail",
    "fallback",
    "refuse",
    "reject",
    "say",
    "think",
    "tool",
    "tools",
]

type Block = dict[str, Any]

_tool_ids = itertools.count(1)
_signatures = itertools.count(1)


@dataclass(frozen=True, slots=True)
class Step:
    content: tuple[Block, ...]
    stop_reason: str
    error: str | None = None  # raise LLMUnavailable (after streaming the content's text)
    rejected: bool = False  # with `error`: raise LLMRejected instead
    declined: str | None = None  # a server-side fallback: this text streamed, then on_reset
    category: str | None = None  # refusal category, reported in ModelCall.error


type Script = Step | Callable[[list[Block]], Step]


def think(text: str = "") -> Block:
    """A thinking block as Claude returns it with display omitted: empty text, a signature."""
    return {"type": "thinking", "thinking": text, "signature": f"sig-{next(_signatures)}"}


def say(text: str) -> Step:
    return Step(({"type": "text", "text": text},), "end_turn")


def tool(name: str, tool_input: dict[str, Any], *, text: str | None = None) -> Step:
    return tools([(name, tool_input)], text=text)


def tools(calls: Sequence[tuple[str, dict[str, Any]]], *, text: str | None = None) -> Step:
    """One response with these tool calls (in order); ids are unique across the process."""
    blocks: list[Block] = [{"type": "text", "text": text}] if text else []
    blocks += [
        {"type": "tool_use", "id": f"toolu_{next(_tool_ids):04d}", "name": name, "input": args}
        for name, args in calls
    ]
    return Step(tuple(blocks), "tool_use")


def refuse(category: str | None = "general_harms", *, after_text: str | None = None) -> Step:
    """A safety refusal: before any output, or mid-stream after `after_text`."""
    content = ({"type": "text", "text": after_text},) if after_text else ()
    return Step(content, "refusal", category=category)


def fail(message: str = "scripted outage", *, after_text: str | None = None) -> Step:
    """No usable answer (LLMUnavailable), optionally after some text was streamed."""
    content = ({"type": "text", "text": after_text},) if after_text else ()
    return Step(content, "error", error=message)


def reject(message: str = "scripted invalid_request_error") -> Step:
    """The API rejects the request itself (LLMRejected, e.g. a bad replayed transcript)."""
    return Step((), "error", error=message, rejected=True)


def fallback(declined_text: str, then: Step) -> Step:
    """A server-side refusal fallback mid-stream: `declined_text` streams, the first model
    declines (on_reset), and the fallback model answers with `then`. The content is what the
    real client returns after stripping: the declined text, the `fallback` block, then the
    fallback model's blocks."""
    marker: Block = {
        "type": "fallback",
        "from": {"model": "fake-chat"},
        "to": {"model": "fake-chat-fallback"},
        "trigger": {"type": "refusal", "category": "cyber"},
    }
    content = ({"type": "text", "text": declined_text}, marker, *then.content)
    return Step(content, then.stop_reason, declined=declined_text)


def chunks(text: str) -> list[str]:
    """Stream-sized pieces that join back to exactly `text`."""
    return re.findall(r"\S+\s*|\s+", text)


@dataclass(slots=True)
class ScriptedChatModel:
    """Answers `respond` from `script`. With `strict` (default) every request is checked like
    the API would: `check_transcript` holds, the last message is a user message, system and
    tools are byte-identical to the previous request's, and the messages start with the
    previous request's messages (append-only) - except after a refused or failed response,
    when they may instead start with the transcript before that turn (the service discards a
    refused turn), after a rejected one, and for a request of one message (a new transcript
    epoch or another thread). `new_epoch()` lifts the prefix check once for other cases."""

    script: list[Script]
    model: str = "fake-chat"
    fallback_model: str = "fake-chat-fallback"
    strict: bool = True
    thinking: bool = True  # prepend think() to every response with content
    requests: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    _prefix: list[str] | None = field(default=None, init=False, repr=False)  # JSON per message
    _before_turn: list[str] | None = field(default=None, init=False, repr=False)
    _discardable: bool = field(default=False, init=False, repr=False)
    _answer: str | None = field(default=None, init=False, repr=False)
    _static: str | None = field(default=None, init=False, repr=False)
    _ids: set[str] = field(default_factory=set[str], init=False, repr=False)

    def new_epoch(self) -> None:
        """The caller starts a fresh transcript (idle gap, long thread): no prefix check."""
        self._prefix = self._before_turn = None

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
        self.requests.append(
            {"system": system, "tools": tools, "messages": copy.deepcopy(list(messages))}
        )
        if self.strict:
            self._check(system, tools, messages)
        if not self.script:
            raise AssertionError("ScriptedChatModel ran out of steps")
        entry = self.script.pop(0)
        step = entry(list(messages)) if callable(entry) else entry
        content = self._content(step)
        streamed = [b for b in content if b["type"] == "text"]
        if step.declined is not None:
            for piece in chunks(step.declined):
                await on_text(piece)
            await on_reset()
            streamed = streamed[1:]
        for block in streamed:
            for piece in chunks(str(block["text"])):
                await on_text(piece)
        call = self._call(step)
        await on_call(call)
        self._discardable = step.error is not None or step.stop_reason == "refusal"
        self._answer = json.dumps({"role": "assistant", "content": content})
        if step.error is not None:
            if step.rejected:
                self.new_epoch()
                raise LLMRejected(step.error)
            raise LLMUnavailable(step.error)
        return Turn(content, step.stop_reason, call)

    def _content(self, step: Step) -> list[Block]:
        blocks = [copy.deepcopy(dict(b)) for b in step.content]
        for block in blocks:
            if block["type"] == "tool_use":
                if block["id"] in self._ids:  # the same Step object scripted twice
                    block["id"] = f"toolu_{next(_tool_ids):04d}"
                self._ids.add(block["id"])
        wants_thinking = self.thinking and blocks and step.error is None
        if wants_thinking and not any(b["type"] == "thinking" for b in blocks):
            at = 2 if step.declined is not None else 0  # the fallback model thinks afresh
            blocks.insert(at, think())
        return blocks

    def _call(self, step: Step) -> ModelCall:
        usage = Usage(input_tokens=100, output_tokens=20)
        status: CallStatus = "ok"
        if step.error is not None:
            status = "error"
        elif step.stop_reason in ("refusal", "max_tokens"):
            status = "refusal" if step.stop_reason == "refusal" else "max_tokens"
        if step.declined is None:
            return ModelCall(
                "chat", self.model, usage, 1, status, error=step.error or step.category
            )
        declined = Usage(input_tokens=100, output_tokens=5)
        return ModelCall(
            "chat",
            self.fallback_model,
            declined + usage,
            1,
            status,
            parts=((self.model, declined), (self.fallback_model, usage)),
        )

    def _check(self, system: list[Block], tools: list[Block], messages: list[Block]) -> None:
        problems = list(check_transcript(messages))
        if not messages or messages[-1].get("role") != "user":
            problems.append("a request must end with a user message")
        try:
            static = json.dumps([system, tools])
            sent = [json.dumps(m) for m in messages]
        except TypeError as e:
            raise AssertionError(f"ScriptedChatModel: request is not JSON: {e}") from e
        if self._static is not None and static != self._static:
            problems.append("system or tools changed since the previous request")
        if self._prefix is not None and len(messages) > 1:  # one message: a new thread/epoch
            extends = _starts_with(sent, self._prefix)
            if extends:  # and the last response, if replayed, is replayed exactly
                n = len(self._prefix)
                replayed = (
                    sent[n] if len(sent) > n and messages[n].get("role") == "assistant" else None
                )
                extends = replayed is None or replayed == self._answer
            if not extends and self._discardable and self._before_turn is not None:
                extends = _starts_with(sent, self._before_turn)
            if not extends:
                problems.append("messages are not an append-only extension of the last request")
        if problems:
            raise AssertionError("ScriptedChatModel: " + "; ".join(problems))
        self._static = static
        self._prefix = sent
        self._before_turn = sent[: _turn_start(messages)]
        self._discardable = False
        self._answer = None


def _starts_with(sent: list[str], prefix: list[str]) -> bool:
    return sent[: len(prefix)] == prefix


def _turn_start(messages: list[Block]) -> int:
    """Index of the current turn's user message (the last user message without tool results)."""
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        content: object = msg.get("content")
        blocks = cast(list[Block], content) if isinstance(content, list) else []
        results = any(b.get("type") == "tool_result" for b in blocks)
        if msg.get("role") == "user" and not results:
            return i
    return 0


@dataclass(slots=True)
class ScriptedStructuredModel:
    """Answers `parse` from a queue: a model instance, None (refusal / unusable), or an
    exception to raise. `answer` may instead be a function of (purpose, prompt)."""

    answers: list[BaseModel | Exception | None] = field(
        default_factory=list[BaseModel | Exception | None]
    )
    answer: Callable[[str, str], BaseModel | None] | None = None
    model: str = "fake-structured"
    prompts: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    async def parse[T: BaseModel](
        self, *, purpose: str, system: str, prompt: str, schema: type[T], on_call: CallSink
    ) -> T | None:
        self.prompts.append((purpose, prompt))
        await on_call(
            ModelCall(purpose, self.model, Usage(input_tokens=50, output_tokens=10), 1, "ok")
        )
        if self.answer is not None:
            got: BaseModel | Exception | None = self.answer(purpose, prompt)
        elif self.answers:
            got = self.answers.pop(0)
        else:
            raise AssertionError("ScriptedStructuredModel ran out of answers")
        if isinstance(got, Exception):
            raise got
        if got is None:
            return None
        return schema.model_validate(got.model_dump())
