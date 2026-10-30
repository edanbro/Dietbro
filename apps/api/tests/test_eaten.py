"""Meals marked eaten (POST/DELETE /plans/{id}/meals/eaten) and plan changes from the plan
screen (POST /plans/replan), through the API. The plan runs Monday 12 to Sunday 18 Oct 2026;
it is Wednesday 14 Oct, 12:00 UTC (app_support)."""

import uuid
from collections.abc import Awaitable, Callable, Coroutine
from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from app_support import AppEnv
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_api.changes import limits
from larder_db import models as db
from larder_db.engine import make_sessionmaker

NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]
MON = date(2026, 10, 12)
TUE, WED, THU, FRI = (MON + timedelta(days=d) for d in range(1, 5))


@pytest.fixture
async def plan_id(menu: dict[str, int], new_user: NewUser, make_plan: MakePlan) -> int:
    user_id = await new_user("user_a")
    return await make_plan(user_id, MON)


async def plan_row(engine: AsyncEngine, plan_id: int | None = None) -> db.MealPlan:
    """A plan version (default: the latest) with its meals' recipes and ingredients."""
    async with make_sessionmaker(engine)() as session:
        query = select(db.MealPlan).options(
            selectinload(db.MealPlan.meals)
            .selectinload(db.PlanMeal.recipe)
            .selectinload(db.Recipe.ingredients)
        )
        query = (
            query.where(db.MealPlan.id == plan_id)
            if plan_id is not None
            else query.order_by(db.MealPlan.id.desc())
        )
        row = await session.scalar(query.limit(1))
        assert row is not None
        return row


def cell(plan: db.MealPlan, on: date, slot: str) -> db.PlanMeal:
    meal = next(
        (m for m in plan.meals if m.day == (on - plan.start_date).days and m.slot == slot), None
    )
    assert meal is not None
    return meal


def main_food(meal: db.PlanMeal) -> tuple[int, int]:
    """(food, grams the meal takes of it): its heaviest ingredient line."""
    recipe = meal.recipe
    line = max(recipe.ingredients, key=lambda x: x.grams or 0)
    assert line.food_id is not None
    servings = recipe.servings or 0
    return line.food_id, planning.portion_grams(line.grams, servings, False) * meal.portions


async def add_pantry(
    engine: AsyncEngine,
    user_id: int,
    food_id: int,
    grams: float,
    quantity: float,
    unit: str,
    expires_on: date | None = None,
    *,
    approx: bool = False,
) -> int:
    async with make_sessionmaker(engine)() as session:
        item = db.PantryItem(
            user_id=user_id,
            food_id=food_id,
            grams=grams,
            quantity=quantity,
            unit=unit,
            approx=approx,
            expires_on=expires_on,
        )
        session.add(item)
        await session.commit()
        return item.id


async def pantry(engine: AsyncEngine) -> dict[int, tuple[float, float]]:
    async with make_sessionmaker(engine)() as session:
        return {i.id: (i.grams, i.quantity) for i in await session.scalars(select(db.PantryItem))}


async def logs(engine: AsyncEngine) -> list[db.MealLog]:
    async with make_sessionmaker(engine)() as session:
        return list(await session.scalars(select(db.MealLog).order_by(db.MealLog.id)))


async def count(engine: AsyncEngine, model: Any) -> int:
    async with make_sessionmaker(engine)() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


def mark_body(on: date, slot: str, today: date = WED) -> dict[str, str]:
    return {"date": on.isoformat(), "slot": slot, "today": today.isoformat()}


async def mark(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, on: date, slot: str, **kw: Any
) -> httpx.Response:
    user = kw.pop("user", "user_a")
    return await api.post(
        f"/plans/{plan_id}/meals/eaten", json=mark_body(on, slot, **kw), headers=env.auth(user)
    )


async def unmark(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, on: date, slot: str, user: str = "user_a"
) -> httpx.Response:
    return await api.delete(
        f"/plans/{plan_id}/meals/eaten",
        params={"date": on.isoformat(), "slot": slot},
        headers=env.auth(user),
    )


# --- marking a meal eaten -------------------------------------------------------------------


async def test_marking_a_meal_eaten_logs_it_and_takes_its_food_from_the_pantry(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    v1 = await plan_row(db_engine, plan_id)
    meal = cell(v1, TUE, "lunch")
    food, need = main_food(meal)
    sooner = await add_pantry(db_engine, v1.user_id, food, 10, 10, "g", WED)
    later = await add_pantry(db_engine, v1.user_id, food, 5000, 5, "kg")

    response = await mark(api, env, plan_id, TUE, "lunch")

    assert response.status_code == 200, response.text
    out = response.json()
    assert (out["status"], out["changed"], out["plan_id"]) == ("eaten", True, plan_id)
    assert out["meal"]["status"] == "eaten"
    assert [(p["pantry_item_id"], p["grams"], p["unit"]) for p in out["pantry"]] == [
        (sooner, 10, "g"),
        (later, need - 10, "kg"),
    ]
    assert out["pantry"][1]["quantity"] == pytest.approx((need - 10) / 1000, abs=0.01)
    items = await pantry(db_engine)
    assert items[sooner] == (0, 0)
    assert items[later][0] == pytest.approx(5000 - (need - 10))
    assert items[later][1] == pytest.approx(5 - (need - 10) / 1000)
    [log] = await logs(db_engine)
    assert (log.kind, log.source, log.plan_id, log.recipe_id) == (
        "eaten",
        "app",
        plan_id,
        meal.recipe_id,
    )
    assert (log.eaten_on, log.slot, log.kcal, log.estimated) == (TUE, "lunch", meal.kcal, False)
    assert log.description == meal.recipe.name
    assert [t["pantry_item_id"] for t in log.pantry_taken] == [sooner, later]
    # No new version; the plan shows the meal eaten, its day's totals unchanged.
    assert await count(db_engine, db.MealPlan) == 1
    plan = (await api.get("/plans/current", headers=env.auth("user_a"))).json()
    tuesday = plan["days"][1]
    assert {m["slot"]: m["status"] for m in tuesday["meals"]}["lunch"] == "eaten"
    assert tuesday["logged"] == []
    assert (
        tuesday["totals"] == planning.PlanStats.model_validate(v1.stats).day_totals[1].model_dump()
    )


async def test_marking_twice_changes_nothing(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    v1 = await plan_row(db_engine, plan_id)
    food, _ = main_food(cell(v1, WED, "breakfast"))
    item = await add_pantry(db_engine, v1.user_id, food, 5000, 5000, "g")
    first = (await mark(api, env, plan_id, WED, "breakfast")).json()
    after_first = await pantry(db_engine)

    again = await mark(api, env, plan_id, WED, "breakfast")

    assert again.status_code == 200
    assert (again.json()["status"], again.json()["changed"]) == ("eaten", False)
    assert again.json()["pantry"] == first["pantry"]
    assert await pantry(db_engine) == after_first
    assert after_first[item][0] < 5000
    assert len(await logs(db_engine)) == 1


async def test_marking_eaten_replaces_an_earlier_log_for_that_meal(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    v1 = await plan_row(db_engine, plan_id)
    async with make_sessionmaker(db_engine)() as session:
        session.add(
            db.MealLog(
                user_id=v1.user_id,
                eaten_on=TUE,
                slot="dinner",
                kind="skipped",
                description="Skipped",
                kcal=0,
                protein_g=0,
                fat_g=0,
                carbs_g=0,
                source="app",
            )
        )
        await session.commit()

    assert (await mark(api, env, plan_id, TUE, "dinner")).status_code == 200

    skipped, eaten = await logs(db_engine)
    assert skipped.voided_at is not None
    assert (eaten.kind, eaten.voided_at) == ("eaten", None)


async def test_pantry_items_that_dont_convert_or_are_approximate(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    """A quantity that no longer converts to grams is skipped; an approximate one is used like
    any other (the planner counts its grams as stock)."""
    v1 = await plan_row(db_engine, plan_id)
    food, need = main_food(cell(v1, TUE, "dinner"))
    vague = await add_pantry(db_engine, v1.user_id, food, 500, 2, "handful", MON)
    approx = await add_pantry(db_engine, v1.user_id, food, 5000, 5000, "g", approx=True)

    out = (await mark(api, env, plan_id, TUE, "dinner")).json()

    assert [p["pantry_item_id"] for p in out["pantry"]] == [approx]
    items = await pantry(db_engine)
    assert items[vague] == (500, 2)
    assert items[approx][0] == pytest.approx(5000 - need)


@pytest.mark.parametrize(
    ("on", "slot", "today", "code"),
    [
        (THU, "lunch", WED, 400),  # a meal not had yet
        (TUE, "lunch", WED + timedelta(days=3), 400),  # an implausible today
        (MON - timedelta(days=1), "lunch", WED, 404),  # not in the plan
    ],
)
async def test_marking_refuses_bad_dates(
    api: httpx.AsyncClient,
    env: AppEnv,
    plan_id: int,
    db_engine: AsyncEngine,
    on: date,
    slot: str,
    today: date,
    code: int,
) -> None:
    response = await mark(api, env, plan_id, on, slot, today=today)

    assert response.status_code == code, response.text
    assert await logs(db_engine) == []


async def test_marking_a_cell_without_a_meal_is_404(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    v1 = await plan_row(db_engine, plan_id)
    async with make_sessionmaker(db_engine)() as session:
        meal = await session.get(db.PlanMeal, cell(v1, TUE, "lunch").id)
        assert meal is not None
        await session.delete(meal)
        await session.commit()

    response = await mark(api, env, plan_id, TUE, "lunch")

    assert response.status_code == 404
    assert "no meal planned" in response.text


async def test_only_the_latest_version_can_be_marked(
    api: httpx.AsyncClient,
    env: AppEnv,
    plan_id: int,
    db_engine: AsyncEngine,
    make_plan: MakePlan,
) -> None:
    v1 = await plan_row(db_engine, plan_id)
    await make_plan(v1.user_id, MON)

    assert (await mark(api, env, plan_id, TUE, "lunch")).status_code == 409
    assert (await unmark(api, env, plan_id, TUE, "lunch")).status_code == 409


async def test_another_user_cannot_mark_or_undo_your_meal(
    api: httpx.AsyncClient,
    env: AppEnv,
    plan_id: int,
    db_engine: AsyncEngine,
    new_user: NewUser,
) -> None:
    v1 = await plan_row(db_engine, plan_id)
    food, _ = main_food(cell(v1, TUE, "lunch"))
    other = await new_user("user_b")
    theirs = await add_pantry(db_engine, other, food, 5000, 5000, "g")
    assert (await mark(api, env, plan_id, TUE, "lunch")).status_code == 200

    assert (await mark(api, env, plan_id, TUE, "dinner", user="user_b")).status_code == 404
    assert (await unmark(api, env, plan_id, TUE, "lunch", user="user_b")).status_code == 404

    assert [log.voided_at for log in await logs(db_engine)] == [None]
    assert (await pantry(db_engine))[theirs] == (5000, 5000)  # never someone else's food


# --- undo -----------------------------------------------------------------------------------


async def test_undo_gives_back_exactly_what_was_taken(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    v1 = await plan_row(db_engine, plan_id)
    food, _ = main_food(cell(v1, TUE, "lunch"))
    await add_pantry(db_engine, v1.user_id, food, 30, 30, "g", TUE)
    await add_pantry(db_engine, v1.user_id, food, 2500, 2.5, "kg")
    before = await pantry(db_engine)
    await mark(api, env, plan_id, TUE, "lunch")

    response = await unmark(api, env, plan_id, TUE, "lunch")

    assert response.status_code == 200
    out = response.json()
    assert (out["status"], out["changed"], out["notes"]) == ("planned", True, [])
    assert out["meal"]["status"] == "planned"
    after = await pantry(db_engine)
    assert after.keys() == before.keys()
    for item, (grams, quantity) in before.items():
        assert after[item] == (pytest.approx(grams), pytest.approx(quantity))
    [log] = await logs(db_engine)
    assert log.voided_at is not None
    assert cell(await plan_row(db_engine, plan_id), TUE, "lunch").status == "planned"

    again = await unmark(api, env, plan_id, TUE, "lunch")

    assert (again.status_code, again.json()["changed"]) == (200, False)
    assert await pantry(db_engine) == after


async def test_undo_never_recreates_a_deleted_pantry_item(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    v1 = await plan_row(db_engine, plan_id)
    food, _ = main_food(cell(v1, TUE, "lunch"))
    item = await add_pantry(db_engine, v1.user_id, food, 5000, 5000, "g")
    await mark(api, env, plan_id, TUE, "lunch")
    assert (await api.delete(f"/pantry/{item}", headers=env.auth("user_a"))).status_code == 204

    out = (await unmark(api, env, plan_id, TUE, "lunch")).json()

    assert out["changed"] is True
    assert [p["remaining_quantity"] for p in out["pantry"]] == [None]
    assert "deleted" in out["notes"][0]
    assert await pantry(db_engine) == {}


async def test_undo_after_the_unit_changed_keeps_the_items_grams_per_unit(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    v1 = await plan_row(db_engine, plan_id)
    food, need = main_food(cell(v1, TUE, "lunch"))
    item = await add_pantry(db_engine, v1.user_id, food, 5000, 5000, "g")
    await mark(api, env, plan_id, TUE, "lunch")
    left = 5000 - need
    patch = {"quantity": left / 1000, "unit": "kg"}
    response = await api.patch(f"/pantry/{item}", json=patch, headers=env.auth("user_a"))
    assert response.status_code == 200, response.text

    await unmark(api, env, plan_id, TUE, "lunch")

    assert (await pantry(db_engine))[item] == (pytest.approx(5000), pytest.approx(5))


# --- replans count what was eaten -------------------------------------------------------------


async def test_a_replan_keeps_meals_marked_eaten_and_counts_them_once(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    v1 = await plan_row(db_engine, plan_id)
    totals = planning.PlanStats.model_validate(v1.stats).day_totals
    tue_lunch, wed_breakfast = cell(v1, TUE, "lunch"), cell(v1, WED, "breakfast")
    await mark(api, env, plan_id, TUE, "lunch")
    await mark(api, env, plan_id, WED, "breakfast")

    response = await replan(api, env, [skip(FRI, "dinner")])

    assert response.status_code == 200, response.text
    v2 = await plan_row(db_engine)
    assert v2.parent_id == plan_id
    for before, on in ((tue_lunch, TUE), (wed_breakfast, WED)):
        after = cell(v2, on, before.slot)
        assert (after.recipe_id, after.portions, after.status) == (
            before.recipe_id,
            before.portions,
            "eaten",
        )
    stats = planning.PlanStats.model_validate(v2.stats)
    assert stats.day_totals[1] == totals[1]  # Tuesday: copied, the eaten lunch counted once
    wed_meals = sum(m.kcal for m in v2.meals if m.day == 2)
    assert stats.day_totals[2].kcal == wed_meals  # the breakfast is a row, not also a log
    assert stats.logged_on(1) == []
    assert stats.logged_on(2) == []
    out = response.json()
    assert not [
        c for c in out["changes"] if (c["date"], c["slot"]) == (WED.isoformat(), "breakfast")
    ]

    # Undo on the new version still finds the mark.
    assert (await unmark(api, env, v2.id, WED, "breakfast")).json()["changed"] is True


async def test_a_wish_for_a_meal_marked_eaten_fails(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    await mark(api, env, plan_id, WED, "lunch")  # lunch isn't over at noon

    out = (await replan(api, env, [swap(WED, "lunch")])).json()

    assert out["results"][0]["status"] == "failed"
    assert "already marked" in out["results"][0]["message"]


async def test_reporting_a_meal_marked_eaten_otherwise_gives_its_food_back(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    v1 = await plan_row(db_engine, plan_id)
    food, _ = main_food(cell(v1, TUE, "dinner"))
    item = await add_pantry(db_engine, v1.user_id, food, 5000, 5000, "g")
    await mark(api, env, plan_id, TUE, "dinner")

    out = (await replan(api, env, [skip(TUE, "dinner")])).json()

    assert out["results"][0]["status"] == "applied"
    eaten, skipped = await logs(db_engine)
    assert (eaten.kind, skipped.kind) == ("eaten", "skipped")
    assert eaten.voided_at is not None
    assert (await pantry(db_engine))[item] == (pytest.approx(5000), pytest.approx(5000))
    v2 = await plan_row(db_engine)
    assert not [m for m in v2.meals if m.day == 1 and m.slot == "dinner"]
    assert cell(await plan_row(db_engine, plan_id), TUE, "dinner").status == "planned"


async def test_a_new_plan_lists_a_meal_eaten_earlier(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    await mark(api, env, plan_id, WED, "breakfast")

    response = await api.post(
        "/plans", json={"start": TUE.isoformat()}, headers=env.auth("user_a")
    )  # a start no earlier than yesterday (the test clock's today is WED)

    assert response.status_code == 201, response.text
    wednesday = response.json()["days"][1]
    assert [(e["kind"], e["slot"]) for e in wednesday["logged"]] == [("eaten", "breakfast")]
    assert "breakfast" not in {m["slot"] for m in wednesday["meals"]}


# --- POST /plans/replan -------------------------------------------------------------------------


def skip(on: date, slot: str, elsewhere: bool = False) -> dict[str, Any]:
    return {
        "intent": "skip",
        "when": {"date": on.isoformat(), "slot": slot},
        "eating_elsewhere": elsewhere,
    }


def swap(on: date, slot: str) -> dict[str, Any]:
    return {"intent": "swap", "when": {"date": on.isoformat(), "slot": slot}}


async def replan(
    api: httpx.AsyncClient,
    env: AppEnv,
    changes: list[dict[str, Any]],
    *,
    client_id: uuid.UUID | None = None,
    today: date = WED,
    user: str = "user_a",
) -> httpx.Response:
    body = {
        "changes": changes,
        "client_id": str(client_id or uuid.uuid4()),
        "today": today.isoformat(),
        "local_time": "12:00",
    }
    return await api.post("/plans/replan", json=body, headers=env.auth(user))


async def test_replan_from_the_plan_screen_makes_a_version(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    client_id = uuid.uuid4()

    response = await replan(
        api, env, [skip(FRI, "dinner"), swap(THU, "dinner")], client_id=client_id
    )

    assert response.status_code == 200, response.text
    assert response.headers["server-timing"].startswith("replan;dur=")
    out = response.json()
    assert out["type"] == "outcome"
    assert [r["status"] for r in out["results"]] == ["applied", "applied"]
    v2 = await plan_row(db_engine)
    assert (out["plan_id"], v2.parent_id) == (v2.id, plan_id)
    assert planning.PlanStats.model_validate(v2.stats).total_ms > 0
    [log] = await logs(db_engine)
    assert (log.kind, log.source, log.craving_id is not None) == ("skipped", "app", True)
    async with make_sessionmaker(db_engine)() as session:
        cravings = list(await session.scalars(select(db.Craving).order_by(db.Craving.id)))
    assert [(c.client_id, c.intent) for c in cravings] == [
        (client_id, "skip"),
        (client_id, "swap"),
    ]


async def test_replan_resent_with_the_same_client_id_is_not_applied_twice(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    client_id = uuid.uuid4()
    assert (await replan(api, env, [skip(FRI, "dinner")], client_id=client_id)).status_code == 200

    again = await replan(api, env, [skip(FRI, "dinner")], client_id=client_id)

    assert again.status_code == 409
    assert again.json()["code"] == "duplicate"
    assert await count(db_engine, db.MealPlan) == 2
    assert await count(db_engine, db.MealLog) == 1


async def test_replan_waits_for_no_one(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    """Another replan holds the user's replan lock: busy, nothing applied."""
    v1 = await plan_row(db_engine, plan_id)
    async with make_sessionmaker(db_engine)() as session:
        assert await limits.acquire_lock(session, v1.user_id, uuid.uuid4(), env.settings, env.now)
        await session.commit()

    response = await replan(api, env, [skip(FRI, "dinner")])

    assert response.status_code == 409
    assert response.json()["code"] == "busy"
    assert await count(db_engine, db.MealPlan) == 1


async def test_replan_releases_the_lock(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    assert (await replan(api, env, [skip(FRI, "dinner")])).status_code == 200
    assert (await replan(api, env, [skip(THU, "dinner")])).status_code == 200


async def test_replan_refuses_an_implausible_today(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int
) -> None:
    response = await replan(api, env, [skip(FRI, "dinner")], today=WED + timedelta(days=5))

    assert response.status_code == 400
    assert response.json()["code"] == "bad_today"


@pytest.mark.parametrize(
    "changes",
    [[], [{"intent": "skip", "when": {"date": "2026-10-16"}}], [{"intent": "dance"}]],
    ids=["none", "missing-field", "unknown-intent"],
)
async def test_replan_validates_the_changes(
    api: httpx.AsyncClient, env: AppEnv, plan_id: int, changes: list[dict[str, Any]]
) -> None:
    assert (await replan(api, env, changes)).status_code == 422


async def test_replan_only_ever_changes_your_own_plan(
    api: httpx.AsyncClient,
    env: AppEnv,
    plan_id: int,
    db_engine: AsyncEngine,
    new_user: NewUser,
) -> None:
    other = await new_user("user_b")

    response = await replan(api, env, [swap(FRI, "dinner")], user="user_b")

    assert response.status_code == 200
    out = response.json()
    assert out["fresh"] is True  # user_b had no plan: a week of their own from today
    async with make_sessionmaker(db_engine)() as session:
        owners = list(await session.scalars(select(db.MealPlan.user_id).order_by(db.MealPlan.id)))
    assert owners == [(await plan_row(db_engine, plan_id)).user_id, other]
    assert (await plan_row(db_engine, out["plan_id"])).parent_id is None


async def test_replan_needs_a_session(api: httpx.AsyncClient, env: AppEnv) -> None:
    body = {"changes": [skip(FRI, "dinner")], "client_id": str(uuid.uuid4()), "today": "2026-10-14"}
    assert (await api.post("/plans/replan", json=body)).status_code == 401
