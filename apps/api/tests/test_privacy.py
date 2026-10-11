"""A recipe drafted for one user is theirs alone (DESIGN §9.4): no other user is planned it,
finds it, opens it or sees its cuisine; anonymous callers get the catalogue only; deleting the
owner's account still works when their own plans use it."""

from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, date, datetime, time
from functools import partial

import httpx
import pytest
from safety import assert_user_safe
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api import planning
from larder_api.chat.handlers import guard_recipe
from larder_api.chat.scope import ChatScope, Models
from larder_api.chat.search import search_recipes
from larder_api.main import app
from larder_api.routers.plans import get_catalog_cache, get_planner
from larder_api.settings import Settings
from larder_core.meals import Slot
from larder_db import models as db
from larder_db.engine import make_sessionmaker
from larder_solver import Plan, PlanResult, Problem, greedy

LENTILS, TOMATO = 172420, 170457
SECRET_CUISINE = "Secretland"

Auth = Callable[..., dict[str, str]]


@pytest.fixture(autouse=True)
def plans_with_greedy() -> Iterator[None]:
    cache = planning.CatalogCache()
    app.dependency_overrides[get_catalog_cache] = lambda: cache
    app.dependency_overrides[get_planner] = lambda: partial(
        planning.run_planner, mode="greedy", time_limit_ms=2000, workers=1
    )
    yield
    app.dependency_overrides.pop(get_catalog_cache, None)
    app.dependency_overrides.pop(get_planner, None)


@pytest.fixture
async def secret(
    db_engine: AsyncEngine,
    menu: dict[str, int],
    new_user: Callable[..., Awaitable[int]],
    add_recipe: Callable[..., Awaitable[int]],
) -> tuple[int, int, int]:
    """(user A, user B, A's generated recipe). Both like its cuisine, so only privacy keeps it
    out of B's plan."""
    a, b = await new_user("user_a"), await new_user("user_b")
    stew = [("lentil", LENTILS, 240), ("tomato", TOMATO, 600)]
    recipe = await add_recipe(
        "Grandma's secret stew", "Vegetarian", 520, 32, stew, owner=a, cuisine=SECRET_CUISINE
    )
    async with make_sessionmaker(db_engine)() as session:
        await session.execute(
            update(db.Preferences)
            .where(db.Preferences.user_id.in_([a, b]))
            .values(liked_cuisines=[SECRET_CUISINE])
        )
        await session.commit()
    return a, b, recipe


def scope(engine: AsyncEngine, user_id: int) -> ChatScope:
    async def nothing(_: object) -> None:
        return None

    return ChatScope(
        user_id=user_id,
        today=date(2026, 10, 14),
        local_time=time(12),
        now=datetime(2026, 10, 14, 12, tzinfo=UTC),
        thread_id=0,
        message_id=0,
        raw_text="",
        sessionmaker=make_sessionmaker(engine),
        catalog=planning.CatalogCache(),
        planner=partial(planning.run_planner, mode="greedy", time_limit_ms=2000, workers=1),
        settings=Settings(),
        models=Models(),
        emit=nothing,
        log_call=nothing,
    )


def recipe_ids(plan: dict[str, object]) -> set[int]:
    days = plan["days"]
    assert isinstance(days, list)
    return {m["recipe"]["id"] for d in days for m in d["meals"]}  # pyright: ignore[reportUnknownVariableType]


async def test_other_users_never_see_a_generated_recipe(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine, secret: tuple[int, int, int]
) -> None:
    a, b, recipe = secret

    plan_b = await api.post("/plans", json={}, headers=auth("user_b"))
    hits_b = await search_recipes(scope(db_engine, b), "secret stew", None)
    hits_a = await search_recipes(scope(db_engine, a), "secret stew", None)

    assert plan_b.status_code == 201, plan_b.text
    assert recipe not in recipe_ids(plan_b.json())
    assert recipe not in {h.id for h in hits_b}
    assert recipe in {h.id for h in hits_a}
    assert (
        await guard_recipe(scope(db_engine, b), recipe, Slot.DINNER) == "I can't use that recipe."
    )
    assert (await api.get(f"/recipes/{recipe}", headers=auth("user_b"))).status_code == 404
    assert (await api.get(f"/recipes/{recipe}")).status_code == 404
    mine = await api.get(f"/recipes/{recipe}", headers=auth("user_a"))
    assert mine.status_code == 200
    assert mine.json()["generated"] is True
    assert SECRET_CUISINE not in (await api.get("/cuisines")).json()
    async with make_sessionmaker(db_engine)() as session:
        await assert_user_safe(session, b, datetime.now(UTC).date())


async def test_a_bad_token_on_the_recipe_page_is_401(
    api: httpx.AsyncClient, secret: tuple[int, int, int]
) -> None:
    response = await api.get("/recipes/1", headers={"Authorization": "Bearer nonsense"})

    assert response.status_code == 401


async def test_the_owner_can_delete_their_account_while_their_plan_uses_it(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine, secret: tuple[int, int, int]
) -> None:
    a, b, recipe = secret
    plan_a = (await api.post("/plans", json={}, headers=auth("user_a"))).json()
    plan_b = (await api.post("/plans", json={}, headers=auth("user_b"))).json()
    async with make_sessionmaker(db_engine)() as session:  # make sure A's plan uses the recipe
        await session.execute(
            update(db.PlanMeal)
            .where(db.PlanMeal.plan_id == plan_a["id"], db.PlanMeal.slot == "dinner")
            .values(recipe_id=recipe)
        )
        await session.commit()

    assert (await api.delete("/me", headers=auth("user_a"))).status_code == 204

    async with make_sessionmaker(db_engine)() as session:
        assert await session.get(db.Recipe, recipe) is None
        assert await session.get(db.User, a) is None
        left = await session.scalars(select(db.MealPlan.id).where(db.MealPlan.user_id == b))
        assert list(left) == [plan_b["id"]]


async def test_the_owners_own_recipes_are_planned_for_them(
    api: httpx.AsyncClient, auth: Auth, secret: tuple[int, int, int]
) -> None:
    _, _, recipe = secret
    seen: list[Problem] = []

    def capturing(problem: Problem, previous: Plan | None) -> PlanResult:
        seen.append(problem)
        return greedy(problem, previous)

    app.dependency_overrides[get_planner] = lambda: capturing

    response = await api.post("/plans", json={}, headers=auth("user_a"))

    assert response.status_code == 201
    [problem] = seen
    assert any(recipe in spec.candidates for spec in problem.slots)
