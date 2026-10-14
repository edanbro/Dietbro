"""Tool handlers bound to one ChatScope (larder_llm.tools.TOOLS -> functions). Each returns
compact JSON for the model (ToolOutcome.content), never raises for user-level problems
(is_error=True with a short reason instead), and touches only `scope.user_id`'s data: every
plan is loaded with `MealPlan.user_id == scope.user_id`, every recipe through `visible_recipe`.

get_plan, get_pantry, explain_meal, explain_plan_diff (reads the stored outcome in PlanStats
v2; the parent is also the user's): read-only views of today onward.
search_recipes: search.search_recipes.
request_replan: replan.apply_changes(source="chat"); appends to scope.outcomes and emits an
`outcome` event.
create_recipe: create.create_recipe; appends to scope.created_recipes and emits `recipe`.
Unknown or invisible ids get the same answer as a missing one ("I can't use that recipe").
"""

import json
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_api.chat import create, replan, search
from larder_api.chat.context import day_lines, latest_plan, money, plan_stats, short_name
from larder_api.chat.scope import ChatScope
from larder_api.prices import price_with_receipts, receipt_prices
from larder_api.schemas import Currency, OutcomeEvent, RecipeEvent
from larder_core.meals import SLOT_ORDER, Slot
from larder_core.regions import local_price, region_for
from larder_db import models as db
from larder_llm.agent import Handler, ToolOutcome
from larder_llm.schemas import (
    CreateRecipeInput,
    ExplainMealInput,
    ExplainPlanDiffInput,
    ReplanInput,
    SearchRecipesInput,
)

CANT_USE = search.CANT_USE
NO_PLAN = "There is no plan yet: the user can make one on the Plan page."
MAX_PANTRY = 40
CURRENCIES: dict[str, Currency] = {"GBP": "GBP", "EUR": "EUR", "USD": "USD"}


async def visible_recipe(scope: ChatScope, recipe_id: int) -> db.Recipe | None:
    """The recipe if it is in the shared catalogue or owned by this user, else None."""
    return await search.visible_recipe(scope, recipe_id)


async def guard_recipe(scope: ChatScope, recipe_id: int, slot: Slot) -> str | None:
    """None if the recipe may be chosen for `slot` for this user: visible, plannable
    (nutrition complete, servings), `slot` among its meal types (recipe_facts), and
    `candidates.allowed` under the user's current profile. Else the user-facing reason."""
    return await search.guard_recipe(scope, recipe_id, slot)


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _ok(value: object) -> ToolOutcome:
    return ToolOutcome(_json(value))


def _error(message: str) -> ToolOutcome:
    return ToolOutcome(message, is_error=True)


def make_handlers(scope: ChatScope) -> dict[str, Handler]:
    async def get_plan(_: BaseModel) -> ToolOutcome:
        return await _get_plan(scope)

    async def get_pantry(_: BaseModel) -> ToolOutcome:
        return await _get_pantry(scope)

    async def search_recipes(tool_input: BaseModel) -> ToolOutcome:
        assert isinstance(tool_input, SearchRecipesInput)
        return await _search(scope, tool_input)

    async def explain_meal(tool_input: BaseModel) -> ToolOutcome:
        assert isinstance(tool_input, ExplainMealInput)
        return await _explain_meal(scope, tool_input)

    async def request_replan(tool_input: BaseModel) -> ToolOutcome:
        assert isinstance(tool_input, ReplanInput)
        outcome = await replan.apply_changes(scope, tool_input.changes, source="chat")
        scope.outcomes.append(outcome)
        await scope.emit(OutcomeEvent.model_validate(outcome.model_dump()))
        return _ok(outcome.model_dump(mode="json", exclude_defaults=True))

    async def create_recipe(tool_input: BaseModel) -> ToolOutcome:
        assert isinstance(tool_input, CreateRecipeInput)
        created = await create.create_recipe(scope, tool_input)
        if created.recipe_id is None:
            return _error("Not saved: " + "; ".join(created.problems))
        name = tool_input.name.strip()
        scope.created_recipes.append((created.recipe_id, name))
        await scope.emit(RecipeEvent(recipe_id=created.recipe_id, name=name))
        return _ok(
            {
                "recipe_id": created.recipe_id,
                "name": name,
                "slot": tool_input.slot,
                "kcal_per_serving": created.kcal_per_serving,
                "allergens": list(created.allergens),
                "note": "Saved for this user only. To put it in the plan, pass this recipe_id "
                "to request_replan.",
            }
        )

    async def explain_plan_diff(tool_input: BaseModel) -> ToolOutcome:
        assert isinstance(tool_input, ExplainPlanDiffInput)
        return await _explain_diff(scope, tool_input.plan_id)

    return {
        "get_plan": get_plan,
        "get_pantry": get_pantry,
        "search_recipes": search_recipes,
        "explain_meal": explain_meal,
        "request_replan": request_replan,
        "create_recipe": create_recipe,
        "explain_plan_diff": explain_plan_diff,
    }


# --- read-only tools --------------------------------------------------------------------------


async def _get_plan(scope: ChatScope) -> ToolOutcome:
    async with scope.sessionmaker() as session:
        plan = await latest_plan(session, scope.user_id)
        goals = await session.get(db.Goals, scope.user_id)
    if plan is None:
        return _ok({"plan": None, "note": NO_PLAN})
    stats = plan_stats(plan)
    offset = (scope.today - plan.start_date).days
    days = [
        {
            "date": f"{line.date:%a} {line.date.isoformat()}",
            "kcal": line.kcal,
            "meals": [
                {
                    "slot": m.slot.value,
                    "recipe_id": m.recipe_id,
                    "name": m.name,
                    "servings": m.servings,
                    "kcal": m.kcal,
                }
                for m in line.meals
            ],
            **({"logged": list(line.logged)} if line.logged else {}),
        }
        for line in day_lines(plan, scope.today)
    ]
    warnings = [
        v.message
        for v in (stats.violations if stats else [])
        if v.hard and (v.day is None or v.day >= offset)
    ]
    end = plan.start_date + timedelta(days=plan.days - 1)
    out: dict[str, Any] = {
        "plan_id": plan.id,
        "version": plan.version,
        "dates": f"{plan.start_date.isoformat()}..{end.isoformat()}",
        "days": days or "the plan ended before today",
    }
    if goals is not None:
        out["targets"] = {
            "kcal": f"{round(goals.kcal_min)}-{round(goals.kcal_max)} per day",
            "calorie_floor": round(goals.calorie_floor),
            **({"protein_g_min": round(goals.protein_g_min)} if goals.protein_g_min else {}),
        }
    if warnings:
        out["warnings"] = warnings
    return _ok(out)


async def _get_pantry(scope: ChatScope) -> ToolOutcome:
    async with scope.sessionmaker() as session:
        items = (
            await session.scalars(
                select(db.PantryItem)
                .where(db.PantryItem.user_id == scope.user_id)
                .order_by(db.PantryItem.expires_on.asc().nulls_last(), db.PantryItem.id)
                .limit(MAX_PANTRY)
                .options(selectinload(db.PantryItem.food))
            )
        ).all()
    return _ok(
        {
            "items": [
                {
                    "food": short_name(p.food.description),
                    "food_id": p.food_id,
                    "amount": f"{p.quantity:g} {p.unit}",
                    **({"expires": p.expires_on.isoformat()} if p.expires_on else {}),
                }
                for p in items
            ]
        }
    )


async def _search(scope: ChatScope, query: SearchRecipesInput) -> ToolOutcome:
    hits = await search.search_recipes(scope, query.query, query.slot, query.limit)
    if not hits:
        return _ok(
            {
                "recipes": [],
                "note": "No safe recipe matched. Try other words, or create_recipe if the user "
                "wants this particular dish.",
            }
        )
    return _ok(
        {
            "recipes": [
                {
                    "id": h.id,
                    "name": h.name,
                    "cuisine": h.cuisine,
                    "slots": [s.value for s in h.slots],
                    "kcal_per_serving": h.kcal_per_serving,
                    "protein_g_per_serving": h.protein_g_per_serving,
                    "matched": list(h.matched),
                    **({"uses_pantry": list(h.uses_pantry)} if h.uses_pantry else {}),
                }
                for h in hits
            ]
        }
    )


async def _explain_meal(scope: ChatScope, query: ExplainMealInput) -> ToolOutcome:
    async with scope.sessionmaker() as session:
        plan = await latest_plan(session, scope.user_id)
        if plan is None:
            return _error(NO_PLAN)
        day = (query.when.date - plan.start_date).days
        if not 0 <= day < plan.days:
            return _error(f"{query.when.date:%a %d %b} isn't in the current plan.")
        meals = sorted(
            (
                m
                for m in plan.meals
                if m.day == day and (query.when.slot is None or m.slot == query.when.slot)
            ),
            key=lambda m: SLOT_ORDER.index(Slot(m.slot)),
        )
        if not meals:
            stats = plan_stats(plan)
            logged = [e.description for e in stats.logged_on(day)] if stats else []
            return _ok({"meal": None, "logged": logged, "note": "No planned meal there."})
        explained = [await _meal_facts(session, scope.user_id, plan, m) for m in meals]
    return _ok({"meals": explained})


async def _meal_facts(
    session: AsyncSession, user_id: int, plan: db.MealPlan, meal: db.PlanMeal
) -> dict[str, Any]:
    recipe = await session.scalar(
        select(db.Recipe)
        .where(db.Recipe.id == meal.recipe_id)
        .options(selectinload(db.Recipe.ingredients))
    )
    assert recipe is not None  # plan_meals.recipe_id is a foreign key
    food_ids = [i.food_id for i in recipe.ingredients if i.food_id is not None]
    foods, info = await planning.load_foods(session, food_ids)
    pantry = (
        await session.scalars(
            select(db.PantryItem)
            .join(db.Food, db.Food.id == db.PantryItem.food_id)
            .where(
                db.PantryItem.user_id == user_id,
                func.coalesce(db.Food.generic_food_id, db.PantryItem.food_id).in_(food_ids),
            )
            .options(selectinload(db.PantryItem.food))
        )
    ).all()
    prefs = await session.get(db.Preferences, user_id)
    user = await session.get(db.User, user_id)
    country = user.country if user is not None else None
    currency = CURRENCIES.get(plan.currency, region_for(country).currency)
    paid = await receipt_prices(session, user_id, date.today())
    cost = 0.0
    for line in recipe.ingredients:
        if line.food_id is None or line.food_id not in info or recipe.servings is None:
            continue
        grams = planning.portion_grams(line.grams, recipe.servings, info[line.food_id].staple)
        food = foods[line.food_id]
        estimate = local_price(
            info[line.food_id].price.pence_per_kg, food.category, country, currency
        )
        per_kg = price_with_receipts(estimate, line.food_id, paid)
        cost += grams * meal.portions * per_kg
    facts: dict[str, Any] = {
        "slot": meal.slot,
        "recipe_id": recipe.id,
        "name": recipe.name,
        "servings": meal.portions / 2,
        "kcal": meal.kcal,
        "protein_g": meal.protein_g,
        "cost_estimate": money(round(cost / 1000), plan.currency),
        "pinned_by_user": meal.locked,
    }
    if recipe.cuisine:
        facts["cuisine"] = recipe.cuisine
        if prefs is not None and recipe.cuisine in prefs.liked_cuisines:
            facts["liked_cuisine"] = True
    used = [
        f"{short_name(p.food.description)}"
        + (f" (expires {p.expires_on.isoformat()})" if p.expires_on else "")
        for p in pantry
    ]
    if used:
        facts["uses_pantry"] = used
    return facts


async def _explain_diff(scope: ChatScope, plan_id: int | None) -> ToolOutcome:
    async with scope.sessionmaker() as session:
        if plan_id is None:
            plan = await latest_plan(session, scope.user_id)
        else:
            plan = await _user_plan(session, scope.user_id, plan_id)
        if plan is None:
            return _error("I can't find that plan version." if plan_id else NO_PLAN)
        parent = (
            await _user_plan(session, scope.user_id, plan.parent_id)
            if plan.parent_id is not None
            else None
        )
    head: dict[str, Any] = {"plan_id": plan.id, "version": plan.version}
    stats = plan_stats(plan)
    if stats is not None and stats.outcome is not None:
        return _ok(head | stats.outcome.model_dump(mode="json", exclude_defaults=True))
    if parent is None:
        return _ok(head | {"note": "This is the first version: there is nothing to compare."})
    return _ok(head | {"parent_id": parent.id, "changes": _diff(parent, plan)})


async def _user_plan(session: AsyncSession, user_id: int, plan_id: int) -> db.MealPlan | None:
    return await session.scalar(
        select(db.MealPlan)
        .where(db.MealPlan.id == plan_id, db.MealPlan.user_id == user_id)
        .options(selectinload(db.MealPlan.meals).selectinload(db.PlanMeal.recipe))
    )


def _diff(before: db.MealPlan, after: db.MealPlan) -> list[dict[str, Any]]:
    """Meal-by-meal differences between two versions (by date, so different starts line up)."""

    def meals(plan: db.MealPlan) -> dict[tuple[str, str], tuple[str, int]]:
        return {
            ((plan.start_date + timedelta(days=m.day)).isoformat(), m.slot): (
                m.recipe.name,
                m.portions,
            )
            for m in plan.meals
        }

    old, new = meals(before), meals(after)
    changes: list[dict[str, Any]] = []
    for key in sorted(old.keys() | new.keys()):
        was, now = old.get(key), new.get(key)
        if was == now:
            continue
        change: dict[str, Any] = {
            "date": key[0],
            "slot": key[1],
            "before": was[0] if was else None,
            "after": now[0] if now else None,
        }
        if was and now and was[1] != now[1]:
            change["servings"] = f"{was[1] / 2:g} -> {now[1] / 2:g}"
        changes.append(change)
    return changes
