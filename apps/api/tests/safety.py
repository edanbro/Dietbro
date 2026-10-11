"""Suite-wide safety check (DESIGN §9.6): recompute, from stored rows only, that nothing planned
for a user conflicts with their current allergies, diet and avoided foods.

It uses the recipe rows, the tagger (larder_core.tagging via planning.recipe_facts) and the
profile rows - never the executor's Problem or the validator - so a bug in the planning path
can't hide itself. Checked:

- every meal of the user's latest plan dated today or later (the current profile applies from
  today on);
- every meal of any version saved after the profile was last changed, except meals carried over
  unchanged from that version's parent (past days and meals already eaten are copied verbatim
  and never re-judged, ADR-0014);
- every recipe the user owns that was created after the profile was last changed.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_core.allergens import Allergen
from larder_core.tagging import Diet, diet_allows
from larder_db import models as db


async def assert_user_safe(session: AsyncSession, user_id: int, today: date) -> None:
    allergies = await session.get(db.Allergies, user_id, populate_existing=True)
    prefs = await session.get(db.Preferences, user_id, populate_existing=True)
    if allergies is None or prefs is None:
        return
    allergens = frozenset(Allergen(a) for a in allergies.allergens)
    avoid = frozenset(allergies.avoid_food_ids)
    diet = Diet(prefs.diet) if prefs.diet else None
    restricted = bool(allergens or avoid or diet)
    changed = max(allergies.updated_at, prefs.updated_at)

    plans = (
        await session.scalars(
            select(db.MealPlan)
            .where(db.MealPlan.user_id == user_id)
            .order_by(db.MealPlan.created_at, db.MealPlan.id)
            .options(selectinload(db.MealPlan.meals)),
            execution_options={"populate_existing": True},
        )
    ).all()
    by_id = {p.id: p for p in plans}
    latest = plans[-1] if plans else None
    to_check: list[tuple[str, int]] = []  # (where, recipe id)
    for plan in plans:
        parent = by_id.get(plan.parent_id) if plan.parent_id is not None else None
        inherited = (
            {(m.day, m.slot): (m.recipe_id, m.portions) for m in parent.meals}
            if parent is not None and parent.start_date == plan.start_date
            else {}
        )
        for meal in plan.meals:
            on = plan.start_date + timedelta(days=meal.day)
            copied = inherited.get((meal.day, meal.slot)) == (meal.recipe_id, meal.portions)
            if (plan is latest and on >= today) or (plan.created_at >= changed and not copied):
                to_check.append(
                    (f"plan {plan.id} v{plan.version} {on} {meal.slot}", meal.recipe_id)
                )
    owned = await session.scalars(
        select(db.Recipe.id).where(
            db.Recipe.owner_user_id == user_id, db.Recipe.created_at >= changed
        )
    )
    to_check += [(f"owned recipe {rid}", rid) for rid in owned]

    recipes = {
        r.id: r
        for r in await session.scalars(
            select(db.Recipe)
            .where(db.Recipe.id.in_({rid for _, rid in to_check}))
            .options(selectinload(db.Recipe.ingredients))
        )
    }
    foods, info = await planning.load_foods(
        session,
        (i.food_id for r in recipes.values() for i in r.ingredients if i.food_id is not None),
    )
    problems: list[str] = []
    for where, rid in to_check:
        recipe = recipes[rid]
        tags = planning.recipe_facts(recipe, foods, info).tags
        food_ids = {i.food_id for i in recipe.ingredients if i.food_id is not None}
        if hit := tags.allergens & allergens:
            problems.append(f"{where}: {recipe.name} contains {sorted(hit)}")
        if not diet_allows(diet, tags.animal):
            problems.append(f"{where}: {recipe.name} isn't {diet} ({sorted(tags.animal)})")
        if hit_foods := food_ids & avoid:
            problems.append(f"{where}: {recipe.name} uses avoided foods {sorted(hit_foods)}")
        if restricted and tags.unresolved:
            problems.append(f"{where}: {recipe.name} has {tags.unresolved} unverified lines")
    assert not problems, "unsafe for the user:\n" + "\n".join(problems)
