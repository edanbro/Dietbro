"""Estimate what an off-plan meal contained: items (or the description as one item) -> foods
(foods.match_food) -> grams (foods.grams_for) -> macros computed from USDA per-100 g values.
The model's own numbers are never used. Unmatched items are reported, not guessed; if nothing
matches, the estimate falls back to the planned meal at that slot (or 600 kcal for a main, 250
for a snack) and says so."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select

from larder_api import planning
from larder_api.changes import foods
from larder_api.changes.scope import ChangeScope
from larder_core.meals import Slot
from larder_db import models as db
from larder_llm.schemas import AteOffPlan, OffPlanItem
from larder_solver import Macros

# A typical meal when nothing in the description matched a food (kcal, protein, fat, carbs).
TYPICAL_MAIN = Macros(600, 25, 25, 65)
TYPICAL_SNACK = Macros(250, 5, 12, 30)


@dataclass(frozen=True, slots=True)
class Estimate:
    macros: Macros
    items: list[dict[str, object]]  # {"name", "food_id", "food", "grams"} per matched item
    unmatched: list[str]
    note: str | None  # "Estimated as a typical dinner - tell me what was in it to be precise."
    estimated: bool = True  # False only when every item matched with an exact amount


async def estimate(scope: ChangeScope, change: AteOffPlan) -> Estimate:
    items = change.items or [OffPlanItem(name=change.description)]
    found: list[tuple[OffPlanItem, foods.FoodMatch, float, bool]] = []
    unmatched: list[str] = []
    for item in items:
        match = await foods.match_food(scope, item.name)
        if match is None:
            unmatched.append(item.name)
            continue
        grams, estimated = await foods.grams_for(scope, match.food_id, item.quantity)
        found.append((item, match, grams, estimated))
    if not found:
        return await _fallback(scope, change, unmatched)

    async with scope.sessionmaker() as session:
        rows = await session.scalars(
            select(db.Food).where(db.Food.id.in_({m.food_id for _, m, _, _ in found}))
        )
        per_100g = {f.id: f for f in rows}
    kcal = protein = fat = carbs = 0.0
    for _, match, grams, _ in found:
        food = per_100g[match.food_id]
        kcal += (food.kcal or 0) * grams / 100
        protein += (food.protein_g or 0) * grams / 100
        fat += (food.fat_g or 0) * grams / 100
        carbs += (food.carbs_g or 0) * grams / 100
    return Estimate(
        macros=Macros(round(kcal), round(protein), round(fat), round(carbs)),
        items=[
            {"name": item.name, "food_id": m.food_id, "food": m.description, "grams": round(g)}
            for item, m, g, _ in found
        ],
        unmatched=unmatched,
        note=None,
        estimated=bool(unmatched) or any(estimated for *_, estimated in found),
    )


def exact(picks: list[tuple[db.Food, float]]) -> Estimate:
    """Food the user picked themselves (diary quick-add): exact foods and grams, no guessing."""
    kcal = protein = fat = carbs = 0.0
    for food, grams in picks:
        kcal += (food.kcal or 0) * grams / 100
        protein += (food.protein_g or 0) * grams / 100
        fat += (food.fat_g or 0) * grams / 100
        carbs += (food.carbs_g or 0) * grams / 100
    return Estimate(
        macros=Macros(round(kcal), round(protein), round(fat), round(carbs)),
        items=[
            {"name": f.description, "food_id": f.id, "food": f.description, "grams": round(g)}
            for f, g in picks
        ],
        unmatched=[],
        note=None,
        estimated=False,
    )


async def _fallback(scope: ChangeScope, change: AteOffPlan, unmatched: list[str]) -> Estimate:
    slot = change.when.slot or Slot.DINNER
    planned = await planned_meal(scope, change.when.date, slot)
    if planned is not None:
        name, macros = planned
        note = f"Estimated as your planned {slot} ({name}) - tell me what was in it to be precise."
        return Estimate(macros, [], unmatched, note)
    typical = TYPICAL_SNACK if slot == Slot.SNACK else TYPICAL_MAIN
    note = f"Estimated as a typical {slot} - tell me what was in it to be precise."
    return Estimate(typical, [], unmatched, note)


async def planned_meal(scope: ChangeScope, on: date, slot: Slot) -> tuple[str, Macros] | None:
    """The planned meal at (date, slot) in the plan in force that day, if it covers the date."""
    async with scope.sessionmaker() as session:
        plan = await planning.plan_for(session, scope.user_id, on)
        if plan is None:
            return None
        day = (on - plan.start_date).days
        meal = next((m for m in plan.meals if m.day == day and m.slot == slot), None)
        if meal is None:
            return None
        recipe = await session.get(db.Recipe, meal.recipe_id)
        name = recipe.name if recipe else "your planned meal"
        return name, Macros(meal.kcal, meal.protein_g, meal.fat_g, meal.carbs_g)
