"""Prep ahead: what tomorrow's planned meals need doing the evening before.

- Defrost: a meal's recipe uses food the user keeps in the freezer (`PantryItem.storage`, or
  where that food usually is). A product or regional food counts as its generic, as for the
  plan's "uses your" hints.
- Start: a step of the method that needs a head start (larder_core.cook_time.ahead_steps:
  marinate overnight, soak the beans for 8 hours, chill for 4 hours).

Shown on the plan (GET /plans/ahead) and sent as an evening push (reminders.send_ahead).
Meals already eaten, and days the plan doesn't cover, need nothing.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_api.schemas import AheadItemOut
from larder_api.storage import kept_in
from larder_core.cook_time import ahead_steps
from larder_core.meals import SLOT_ORDER, Slot
from larder_db import models as db


async def ahead_for(session: AsyncSession, user_id: int, day: date) -> list[AheadItemOut]:
    """What to do the evening before `day` for its planned meals, in meal order: what to take
    out of the freezer, then what to start."""
    plan = await planning.plan_for(session, user_id, day)
    if plan is None:
        return []
    index = (day - plan.start_date).days
    if not 0 <= index < plan.days:
        return []
    meals = sorted(
        (m for m in plan.meals if m.day == index and m.status != "eaten"),
        key=lambda m: SLOT_ORDER.index(Slot(m.slot)),
    )
    if not meals:
        return []
    recipes = {
        r.id: r
        for r in await session.scalars(
            select(db.Recipe)
            .where(db.Recipe.id.in_({m.recipe_id for m in meals}))
            .options(selectinload(db.Recipe.ingredients))
        )
    }
    frozen: dict[int, str] = {}  # food id (and its generic) -> what the user calls it
    for item in await session.scalars(
        select(db.PantryItem)
        .where(db.PantryItem.user_id == user_id, db.PantryItem.grams > 0)
        .options(selectinload(db.PantryItem.food))
        .order_by(db.PantryItem.id)
    ):
        if kept_in(item) != "freezer":
            continue
        frozen.setdefault(item.food_id, item.food.description)
        if item.food.generic_food_id is not None:
            frozen.setdefault(item.food.generic_food_id, item.food.description)

    defrost: list[AheadItemOut] = []
    start: list[AheadItemOut] = []
    named: set[str] = set()
    for meal in meals:
        recipe = recipes.get(meal.recipe_id)
        if recipe is None:
            continue
        slot = Slot(meal.slot)
        for line in recipe.ingredients:
            food = frozen.get(line.food_id) if line.food_id is not None else None
            if food is not None and food not in named:
                named.add(food)
                defrost.append(
                    AheadItemOut(
                        kind="defrost",
                        slot=slot,
                        recipe_id=recipe.id,
                        recipe_name=recipe.name,
                        text=food,
                    )
                )
        start.extend(
            AheadItemOut(
                kind="start", slot=slot, recipe_id=recipe.id, recipe_name=recipe.name, text=step
            )
            for step in ahead_steps(recipe.instructions)
        )
    return [*defrost, *start]
