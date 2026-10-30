"""A scripted stand-in for the structured model client, for tests and offline demos. No network.

fast = ScriptedStructuredModel([FoodPick(food_id=170000)])
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from larder_llm.client import CallSink, ModelCall, Usage

__all__ = ["ScriptedStructuredModel"]


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
