"""Vitamins and minerals on plans and recipes: per meal from the recipe's per-serving values,
day and week totals only when every meal's value is known."""

import httpx
import pytest
import test_plans
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine
from test_plans import Auth, set_up

from larder_db.engine import make_sessionmaker
from larder_db.models import Recipe

# test_plans' fixtures: its recipe catalogue, and the greedy planner (autouse there and here).
catalog_db = test_plans.catalog_db
overrides = test_plans.overrides


async def test_meals_days_and_the_week_carry_vitamins_and_minerals(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    async with make_sessionmaker(db_engine)() as session:
        await session.execute(update(Recipe).values(iron_mg=2.0, vitamin_c_mg=10.0))
        await session.commit()
    await set_up(api, auth)

    plan = (await api.post("/plans", json={}, headers=auth())).json()

    day = plan["days"][0]
    for meal in day["meals"]:
        assert meal["nutrition"]["iron_mg"] == pytest.approx(2.0 * meal["servings"])
        assert meal["nutrition"]["vitamin_d_ug"] is None  # no value: unknown, not zero
    assert day["totals"]["iron_mg"] == pytest.approx(
        sum(m["nutrition"]["iron_mg"] for m in day["meals"]), abs=0.01
    )
    assert day["totals"]["vitamin_d_ug"] is None
    assert plan["week_totals"]["iron_mg"] == pytest.approx(
        sum(d["totals"]["iron_mg"] for d in plan["days"]), abs=0.05
    )
    recipe = day["meals"][0]["recipe"]["id"]
    detail = (await api.get(f"/recipes/{recipe}")).json()
    assert detail["per_serving"]["iron_mg"] == 2.0


async def test_one_unknown_meal_makes_the_day_unknown(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    async with make_sessionmaker(db_engine)() as session:
        await session.execute(update(Recipe).values(iron_mg=2.0))
        # Breakfasts: no iron value.
        await session.execute(
            update(Recipe).where(Recipe.category == "Breakfast").values(iron_mg=None)
        )
        await session.commit()
    await set_up(api, auth)

    plan = (await api.post("/plans", json={}, headers=auth())).json()

    day = plan["days"][0]
    assert day["totals"]["iron_mg"] is None  # a sum without breakfast would look like too little
    assert plan["week_totals"]["iron_mg"] is None
