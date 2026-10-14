"""The LLM-only baseline: the question "can't a model just plan the week?" answered with data.

Claude gets the whole problem as JSON - every candidate recipe per slot with its macros per
portion, ingredients and what it contains (allergens and animal products, the same tags the
hybrid planner uses), the user's allergies, diet and avoided foods, the kcal and macro bands,
the budget, the pantry with expiry days, portion and repeat limits - and answers with the meals.
Nothing is filtered for it: unsafe "decoy" recipes stay in the lists, as they would in a real
recipe database. Its plan is then scored by the same validator as the hybrid planner's.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from larder_llm.client import ModelCall, StructuredModel
from larder_llm.pricing import call_cost_micro_usd
from larder_solver import Meal, Plan, PlanResult, Problem, Slot, Status

__all__ = ["LLMPlanner", "PlanAnswer", "PlannedMeal", "problem_json"]

SYSTEM = (
    "You are a meal planner. Plan the user's meals from the candidate recipes given, following "
    "every rule exactly: never use a recipe containing one of the user's allergens, an avoided "
    "food, or an animal product their diet excludes; recipes marked unverified only when the "
    "user has no allergies, diet or avoided foods; fill every required slot every day (optional "
    "slots may stay empty); portions within the limits; each recipe at most max_repeats times; "
    "each day's kcal inside the daily band and at least the calorie floor; the weekly bands and "
    "the budget for the whole plan. Prefer recipes using pantry food that expires soon, liked "
    "recipes (higher preference) and variety. Answer only with the meals."
)


class PlannedMeal(BaseModel):
    day: int = Field(description="0-based day of the plan")
    slot: Literal["breakfast", "lunch", "dinner", "snack"]
    recipe_id: int
    portions: int = Field(description="half-servings, as in the limits")


class PlanAnswer(BaseModel):
    meals: list[PlannedMeal]


def _contains(problem: Problem, recipe_id: int) -> dict[str, Any]:
    recipe = problem.recipes[recipe_id]
    allergens = set(recipe.text_allergens)
    animal = set(recipe.text_animal)
    names: list[str] = []
    for i in recipe.ingredients:
        food = problem.foods.get(i.food_id)
        if food is None:
            names.append(f"unknown food {i.food_id}")
            continue
        allergens |= food.allergens
        animal |= food.animal
        names.append(f"{food.name} {i.grams} g" if i.grams else food.name)
    out: dict[str, Any] = {
        "id": recipe.id,
        "name": recipe.name,
        "per_portion": {
            "kcal": recipe.per_portion.kcal,
            "protein_g": recipe.per_portion.protein_g,
            "fat_g": recipe.per_portion.fat_g,
            "carbs_g": recipe.per_portion.carbs_g,
        },
        "ingredients": names,
        "contains": sorted(a.value for a in allergens),
        "animal_products": sorted(a.value for a in animal),
        "preference": recipe.preference,
    }
    if recipe.unresolved:
        out["unverified"] = True
    return out


def _band(band: Any) -> dict[str, int | None] | None:
    return None if band is None else {"min": band.min, "max": band.max}


def problem_json(problem: Problem) -> str:
    """The problem as the model sees it (compact JSON)."""
    p = problem
    ids = sorted(
        {r for s in p.slots for r in s.candidates} | {r for c in p.choices.values() for r in c}
    )
    data: dict[str, Any] = {
        "days": p.days,
        "start": p.start.isoformat(),
        "slots": [
            {
                "slot": s.slot.value,
                "required": s.required,
                "candidates": list(s.candidates),
                "portions": [s.min_portions or p.min_portions, s.max_portions or p.max_portions],
                "max_repeats": s.max_repeats or p.max_repeats,
            }
            for s in p.slots
        ],
        "user": {
            "allergies": sorted(a.value for a in p.profile.allergens),
            "diet": p.profile.diet.value if p.profile.diet else None,
            "avoided_food_ids": sorted(p.profile.avoid_food_ids),
        },
        "targets": {
            "daily": {n.value: _band(b) for n, b in p.targets.daily.items()},
            "weekly": {n.value: _band(b) for n, b in p.targets.weekly.items()},
            "calorie_floor": p.targets.calorie_floor,
        },
        "budget_minor_units": p.budget,
        "pantry": [
            {
                "food": p.foods[lot.food_id].name if lot.food_id in p.foods else lot.food_id,
                "grams": lot.grams,
                "expires_in_days": lot.expires,
            }
            for lot in p.pantry
        ],
        "already_eaten_kcal_by_day": {str(d): m.kcal for d, m in p.extra.items()},
        "fixed": [
            {"day": d, "slot": s.value, "recipe_id": m.recipe_id if m else None}
            for (d, s), m in p.locked.items()
        ],
        "must_choose_from": [
            {"day": d, "slot": s.value, "recipe_ids": list(r)} for (d, s), r in p.choices.items()
        ],
        "recipes": [_contains(p, r) for r in ids if r in p.recipes],
    }
    return json.dumps(data, separators=(",", ":"))


@dataclass(slots=True)
class LLMPlanner:
    """Plans with `model` (a StructuredModel); keeps the cost of every call it made."""

    model: StructuredModel
    calls: list[ModelCall] = field(default_factory=list[ModelCall])

    @property
    def cost_micro_usd(self) -> int:
        return sum(call_cost_micro_usd(c) for c in self.calls)

    async def plan_async(self, problem: Problem) -> tuple[PlanResult, int]:
        """The plan and the cost of making it (micro-dollars)."""
        before = len(self.calls)

        async def keep(call: ModelCall) -> None:
            self.calls.append(call)

        started = time.perf_counter()
        try:
            answer = await self.model.parse(
                purpose="eval_baseline",
                system=SYSTEM,
                prompt=problem_json(problem),
                schema=PlanAnswer,
                on_call=keep,
            )
        except Exception:
            answer = None
        wall = round((time.perf_counter() - started) * 1000)
        cost = sum(call_cost_micro_usd(c) for c in self.calls[before:])
        if answer is None:
            return PlanResult(Status.UNKNOWN, None, "llm", wall), cost
        meals = tuple(Meal(m.day, Slot(m.slot), m.recipe_id, m.portions) for m in answer.meals)
        return PlanResult(Status.FEASIBLE, Plan(meals), "llm", wall), cost

    def plan(self, problem: Problem) -> tuple[PlanResult, int]:
        return asyncio.run(self.plan_async(problem))
