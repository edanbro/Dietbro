"""The CI slice of the evals: 20 synthetic scenarios through the hybrid planner, and the LLM
baseline's plumbing with a scripted model (no API calls)."""

import json
from pathlib import Path
from typing import Any

import pytest
from larder_evals.baseline import LLMPlanner, PlanAnswer, problem_json
from larder_evals.report import bar_chart, render, summary
from larder_evals.run import hybrid, score, synthetic_scenarios
from pydantic import BaseModel

from larder_llm.client import CallSink, ModelCall, Usage


@pytest.fixture(scope="module")
def hybrid_results() -> list[Any]:
    planner = hybrid("greedy", time_limit_ms=2_000, workers=1)
    items = list(synthetic_scenarios(7, kinds=("planted", "realistic", "replans")))[:20]
    return [score(item, "hybrid", planner) for item in items]


def test_hybrid_plans_are_never_unsafe(hybrid_results: list[Any]) -> None:
    assert len(hybrid_results) == 20
    assert all(r.found for r in hybrid_results)
    assert sum(r.safety_violations for r in hybrid_results) == 0
    assert sum(r.unknown_recipes for r in hybrid_results) == 0
    planted = [r for r in hybrid_results if r.kind == "planted"]
    assert all(r.valid for r in planted)  # a valid plan is known to exist for these


def test_replans_report_churn(hybrid_results: list[Any]) -> None:
    replans = [r for r in hybrid_results if r.kind == "replans"]
    assert replans
    assert all(r.churn is not None for r in replans)


class ScriptedModel:
    """Answers with a fixed plan; reports one call like the real client."""

    def __init__(self, answer: PlanAnswer | None) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def parse[T: BaseModel](
        self, *, purpose: str, system: str, prompt: str, schema: type[T], on_call: CallSink
    ) -> T | None:
        self.prompts.append(prompt)
        await on_call(ModelCall(purpose, "claude-sonnet-5-5", Usage(10_000, 2_000), 1_000, "ok"))
        return self.answer  # type: ignore[return-value]


def test_llm_baseline_is_scored_by_the_validator() -> None:
    item = next(synthetic_scenarios(1, seed=3, kinds=("planted",)))
    problem = item.scenario.problem
    witness = item.scenario.witness
    assert witness is not None
    decoy = next(iter(item.scenario.decoys))
    good = PlanAnswer.model_validate(
        {
            "meals": [
                {
                    "day": m.day,
                    "slot": m.slot.value,
                    "recipe_id": m.recipe_id,
                    "portions": m.portions,
                }
                for m in witness.meals
            ]
        }
    )
    bad = good.model_copy(deep=True)
    bad.meals[0].recipe_id = decoy  # an unsafe decoy
    bad.meals[1].recipe_id = 999_999_999  # made up

    model = ScriptedModel(good)
    ok = score(item, "llm", lambda pr, _prev: LLMPlanner(model).plan(pr))
    model.answer = bad
    unsafe = score(item, "llm", lambda pr, _prev: LLMPlanner(model).plan(pr))

    assert ok.valid
    assert ok.safety_violations == 0
    assert ok.cost_micro_usd == 10_000 * 2 + 2_000 * 10  # $2 / $10 per million tokens
    assert not unsafe.valid
    assert unsafe.unknown_recipes == 1
    data = json.loads(model.prompts[0])
    assert {r["id"] for r in data["recipes"]} >= {decoy}  # the decoy was offered, not hidden
    assert data["user"]["allergies"] or data["user"]["diet"] or data["user"]["avoided_food_ids"]
    assert problem_json(problem) == model.prompts[0]


def test_no_answer_counts_as_no_plan() -> None:
    item = next(synthetic_scenarios(1, kinds=("planted",)))
    result = score(item, "llm", lambda pr, _prev: LLMPlanner(ScriptedModel(None)).plan(pr))
    assert (result.found, result.valid) == (False, False)


def test_report_and_charts(hybrid_results: list[Any], tmp_path: Path) -> None:
    text = render(hybrid_results, tmp_path, source="tests", notes=["a note"])
    assert "| Hybrid (solver plans) | 20 |" in text
    assert (tmp_path / "charts" / "valid.svg").read_text(encoding="utf-8").startswith("<svg")
    assert summary(hybrid_results)["unsafe_pct"] == 0
    svg = bar_chart("t", ["a", "b"], {"hybrid": [50.0, float("nan")]})
    assert svg.count("<rect") == 2  # one bar (nan skipped) + one legend swatch
