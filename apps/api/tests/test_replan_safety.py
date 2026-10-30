"""Adversarial plan changes (DESIGN §9.6): a request - or a model resolving an ingredient name -
tries to put unsafe or foreign recipes in the plan, to save recipes with disguised allergens, or
to rewrite a past day. Nothing unsafe may be saved; the `env` fixture also runs assert_user_safe
for every user after each test."""

import uuid
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, date, datetime, time
from typing import Any

import httpx
import pytest
from app_support import MON, NOW, THU, WED, AppEnv
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api import planning
from larder_api.changes.create import create_recipe
from larder_api.changes.foods import FoodPick
from larder_api.changes.scope import ChangeScope, Models
from larder_api.settings import Settings
from larder_core.meals import Slot
from larder_db import models as db
from larder_db.engine import make_sessionmaker
from larder_llm.client import ModelCall
from larder_llm.fake import ScriptedStructuredModel
from larder_llm.schemas import CreateRecipeInput, DraftIngredient
from larder_solver import Plan, PlanResult, Problem, greedy

NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]
AddRecipe = Callable[..., Awaitable[int]]
LENTILS, TOMATO = 172420, 170457
GHEE, PEANUT_OIL, SATAY_SAUCE = 171314, 1750348, 1_900_002
# Foods the disguised names resolve to, the way the full USDA database would let them.
DISGUISED = [
    (GHEE, "Butter, Clarified butter (ghee)", "Dairy and Egg Products", 876, 99),
    (PEANUT_OIL, "Oil, peanut (groundnut), salad or cooking", "Fats and Oils", 884, 100),
    (SATAY_SAUCE, "Sauce, peanut satay, ready-to-serve", "Soups, Sauces, and Gravies", 300, 20),
]


def planner(problem: Problem, previous: Plan | None) -> PlanResult:
    return greedy(problem, previous)


@pytest.fixture
async def user(menu: dict[str, int], new_user: NewUser, make_plan: MakePlan) -> int:
    user_id = await new_user("user_a", allergens=["peanuts"])
    await make_plan(user_id, MON)
    return user_id


def when(on: date, slot: str) -> dict[str, str]:
    return {"date": on.isoformat(), "slot": slot}


async def replan(api: httpx.AsyncClient, env: AppEnv, *changes: dict[str, Any]) -> Any:
    body = {
        "changes": list(changes),
        "client_id": str(uuid.uuid4()),
        "today": WED.isoformat(),
        "local_time": "12:00",
    }
    response = await api.post("/plans/replan", json=body, headers=env.auth("user_a"))
    assert response.status_code == 200, response.text
    return response.json()


async def planned_recipes(engine: AsyncEngine, user_id: int) -> set[int]:
    async with make_sessionmaker(engine)() as session:
        return set(
            await session.scalars(
                select(db.PlanMeal.recipe_id)
                .join(db.MealPlan, db.MealPlan.id == db.PlanMeal.plan_id)
                .where(db.MealPlan.user_id == user_id)
            )
        )


@pytest.mark.parametrize(
    ("recipe", "slot"),
    [("Satay rice", "dinner"), ("Peanut porridge", "breakfast"), ("Apple and peanuts", "snack")],
)
async def test_a_craving_cant_plan_an_allergen(
    api: httpx.AsyncClient,
    env: AppEnv,
    user: int,
    menu: dict[str, int],
    db_engine: AsyncEngine,
    recipe: str,
    slot: str,
) -> None:
    unsafe = menu[recipe]
    change = {"intent": "craving", "when": when(THU, slot), "strength": "hard"}

    outcome = await replan(api, env, change | {"recipe_id": unsafe})

    assert [r["status"] for r in outcome["results"]] == ["failed"]
    assert unsafe not in await planned_recipes(db_engine, user)


async def test_a_craving_by_name_cant_plan_an_allergen_either(
    api: httpx.AsyncClient, env: AppEnv, user: int, menu: dict[str, int], db_engine: AsyncEngine
) -> None:
    change = {"intent": "craving", "when": when(WED, "dinner"), "dish": "peanut satay"}

    outcome = await replan(api, env, change | {"strength": "hard"})

    assert [r["status"] for r in outcome["results"]] == ["failed"]
    planned = await planned_recipes(db_engine, user)
    assert not planned & {menu["Satay rice"], menu["Peanut porridge"], menu["Apple and peanuts"]}


async def test_a_swap_cant_use_another_users_recipe(
    api: httpx.AsyncClient,
    env: AppEnv,
    user: int,
    new_user: NewUser,
    add_recipe: AddRecipe,
    db_engine: AsyncEngine,
) -> None:
    other = await new_user("user_b")
    stew = [("lentil", LENTILS, 240), ("tomato", TOMATO, 600)]
    theirs = await add_recipe("B's secret stew", "Vegetarian", 520, 30, stew, owner=other)

    swap = {"intent": "swap", "when": when(THU, "dinner"), "recipe_id": theirs}

    outcome = await replan(api, env, swap)

    assert outcome["results"][0]["status"] == "failed"
    assert outcome["results"][0]["message"] == "I can't use that recipe."
    assert theirs not in await planned_recipes(db_engine, user)


@pytest.mark.parametrize(
    ("allergens", "diet", "name", "extra", "reason"),
    [
        (["peanuts"], None, "Chicken satay", ("satay sauce", "4 tbsp"), "it contains peanuts"),
        (
            ["peanuts"],
            None,
            "Stir-fried chicken rice",
            ("groundnut oil", "2 tbsp"),
            "it contains peanuts",
        ),
        ([], "vegan", "Broccoli rice bowl", ("ghee", "1 tbsp"), "it isn't vegan"),
    ],
    ids=["satay sauce", "groundnut oil", "ghee for a vegan"],
)
@pytest.mark.usefixtures("menu", "foods")  # the menu's foods, plus olive oil
async def test_a_recipe_with_a_disguised_allergen_isnt_saved(
    new_user: NewUser,
    db_engine: AsyncEngine,
    allergens: list[str],
    diet: str | None,
    name: str,
    extra: tuple[str, str],
    reason: str,
) -> None:
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            db.Food(id=fid, description=d, data_type="sr_legacy", category=c, kcal=k, fat_g=f)
            for fid, d, c, k, f in DISGUISED
        )
        await session.commit()
    user_id = await new_user("user_a", allergens=allergens, diet=diet)
    lines = [("rice", "150 g"), ("broccoli", "200 g"), ("chicken", "300 g"), extra]
    if diet is not None:
        lines.remove(("chicken", "300 g"))
    draft = CreateRecipeInput(
        name=name,
        slot=Slot.DINNER,
        servings=2,
        ingredients=[DraftIngredient(name=n, quantity=q) for n, q in lines],
        instructions="Cook the rice, stir-fry the rest, serve together.",
    )

    async def log_call(_: ModelCall) -> None:
        return None

    # The fast model resolves an ambiguous name to the food it really is.
    fast = ScriptedStructuredModel(
        answer=lambda _, prompt: FoodPick(
            food_id=next((f for f, *_ in DISGUISED if str(f) in prompt), None)
        )
    )
    scope = ChangeScope(
        user_id=user_id,
        today=NOW.date(),
        local_time=time(12),
        now=datetime(2026, 10, 14, 12, tzinfo=UTC),
        sessionmaker=make_sessionmaker(db_engine),
        catalog=planning.CatalogCache(),
        planner=planner,
        settings=Settings(),
        models=Models(fast=fast),
        log_call=log_call,
    )

    created = await create_recipe(scope, draft)

    assert created.recipe_id is None
    assert any(reason in p for p in created.problems), created.problems  # unsafe, not unknown
    async with make_sessionmaker(db_engine)() as session:
        owned = await session.scalar(
            select(func.count(db.Recipe.id)).where(db.Recipe.owner_user_id == user_id)
        )
    assert owned == 0


async def test_a_swap_on_a_past_day_cant_unplan_history(
    api: httpx.AsyncClient, env: AppEnv, user: int, db_engine: AsyncEngine
) -> None:
    async with make_sessionmaker(db_engine)() as session:
        before = set(
            await session.scalars(
                select(db.PlanMeal.recipe_id).where(db.PlanMeal.day == 0)  # Monday
            )
        )

    outcome = await replan(api, env, {"intent": "swap", "when": when(MON, "dinner")})

    assert outcome["results"][0]["status"] == "failed"
    async with make_sessionmaker(db_engine)() as session:
        latest = await session.scalar(
            select(db.MealPlan).order_by(db.MealPlan.created_at.desc(), db.MealPlan.id.desc())
        )
        assert latest is not None
        monday = set(
            await session.scalars(
                select(db.PlanMeal.recipe_id).where(
                    db.PlanMeal.plan_id == latest.id, db.PlanMeal.day == 0
                )
            )
        )
    assert monday == before
