"""Scripted stand-ins for the model clients, for tests and offline demos. No network.

    chat = ScriptedChatModel([
        tool("search_recipes", {"query": "spicy", "slot": "dinner"}),
        tool("request_replan", {"changes": [...]}),
        say("Done - Thursday is now a chilli."),
    ])

Each scripted step is one assistant response. A step may also be a callable that receives the
messages sent so far and returns a response, so a test can react to tool results.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from larder_llm.client import LLMUnavailable, ModelCall, TextSink, Turn, Usage

__all__ = [
    "Script",
    "ScriptedChatModel",
    "ScriptedStructuredModel",
    "Step",
    "fail",
    "refuse",
    "say",
    "tool",
    "tools",
]

type Block = dict[str, Any]


@dataclass(frozen=True, slots=True)
class Step:
    content: tuple[Block, ...]
    stop_reason: str
    error: str | None = None  # raise LLMUnavailable instead of answering


type Script = Step | Callable[[list[Block]], Step]


def say(text: str) -> Step:
    return Step(({"type": "text", "text": text},), "end_turn")


def tool(name: str, tool_input: dict[str, Any], *, text: str | None = None) -> Step:
    return tools([(name, tool_input)], text=text)


def tools(calls: Sequence[tuple[str, dict[str, Any]]], *, text: str | None = None) -> Step:
    blocks: list[Block] = [{"type": "text", "text": text}] if text else []
    blocks += [
        {"type": "tool_use", "id": f"toolu_{i:02d}_{name}", "name": name, "input": tool_input}
        for i, (name, tool_input) in enumerate(calls)
    ]
    return Step(tuple(blocks), "tool_use")


def refuse() -> Step:
    return Step((), "refusal")


def fail(message: str = "scripted outage") -> Step:
    return Step((), "error", error=message)


@dataclass(slots=True)
class ScriptedChatModel:
    script: list[Script]
    model: str = "fake-chat"
    requests: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    async def respond(
        self,
        *,
        system: list[Block],
        tools: list[Block],
        messages: list[Block],
        on_text: TextSink,
    ) -> Turn:
        self.requests.append({"system": system, "tools": tools, "messages": list(messages)})
        if not self.script:
            raise AssertionError("ScriptedChatModel ran out of steps")
        entry = self.script.pop(0)
        step = entry(list(messages)) if callable(entry) else entry
        call = ModelCall(
            purpose="chat",
            model=self.model,
            usage=Usage(input_tokens=100, output_tokens=20),
            latency_ms=1,
            status="error" if step.error else _status(step.stop_reason),
        )
        if step.error is not None:
            raise LLMUnavailable(step.error, call)
        for block in step.content:
            if block["type"] == "text":
                for word in str(block["text"]).split(" "):
                    await on_text(word + " ")
        return Turn([dict(b) for b in step.content], step.stop_reason, call)


def _status(stop_reason: str) -> Any:
    return {"refusal": "refusal", "max_tokens": "max_tokens"}.get(stop_reason, "ok")


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
        self, *, purpose: str, system: str, prompt: str, schema: type[T]
    ) -> tuple[T | None, list[ModelCall]]:
        self.prompts.append((purpose, prompt))
        call = ModelCall(purpose, self.model, Usage(input_tokens=50, output_tokens=10), 1, "ok")
        if self.answer is not None:
            got: BaseModel | Exception | None = self.answer(purpose, prompt)
        elif self.answers:
            got = self.answers.pop(0)
        else:
            raise AssertionError("ScriptedStructuredModel ran out of answers")
        if isinstance(got, Exception):
            raise got
        if got is None:
            return None, [call]
        return schema.model_validate(got.model_dump()), [call]
