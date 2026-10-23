"""Prep ahead: GET /plans/ahead (larder_api.prep_ahead), its evening push (reminders.send_ahead)
and where pantry food is kept (PATCH /pantry/{id} storage). It is Wednesday 14 October 2026."""

from collections.abc import Awaitable, Callable, Coroutine, Iterator
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import selectinload

from larder_api.clock import get_clock
from larder_api.main import app
from larder_api.reminders import Reminder, ahead_reminder, generate_vapid_keys, send_ahead
from larder_api.schemas import AheadItemOut
from larder_api.settings import Settings
from larder_core.meals import SLOT_ORDER, Slot
from larder_db import models as db
from larder_db.engine import make_sessionmaker

Auth = Callable[..., dict[str, str]]
NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]

pytestmark = pytest.mark.usefixtures("menu")

TODAY, TOMORROW = date(2026, 10, 14), date(2026, 10, 15)
KEYS = generate_vapid_keys()
SETTINGS = Settings.model_validate(
    {"vapid_public_key": KEYS[0], "vapid_private_key": KEYS[1], "ahead_hour": 19}
)
# 18:00 UTC is 19:00 in Dublin (Irish summer time until 25 October).
SEVEN_PM = datetime(2026, 10, 14, 18, 0, tzinfo=UTC)
METHOD = "Mix everything.\nMarinate overnight in the fridge.\nRoast for 30 minutes."


@pytest.fixture(autouse=True)
def clock() -> Iterator[None]:
    app.dependency_overrides[get_clock] = lambda: lambda: datetime(2026, 10, 14, 12, tzinfo=UTC)
    yield
    app.dependency_overrides.pop(get_clock, None)


class Tomorrow:
    """User A's first meal tomorrow: its recipe (now marinated overnight) and a food it uses."""

    user_id: int
    recipe_id: int
    recipe_name: str
    food_id: int
    food: str
    slot: Slot


async def plan_tomorrow(db_engine: AsyncEngine, new_user: NewUser, make_plan: MakePlan) -> Tomorrow:
    t = Tomorrow()
    t.user_id = await new_user("user_a")
    async with make_sessionmaker(db_engine)() as session:
        await session.execute(
            update(db.User).where(db.User.id == t.user_id).values(timezone="Europe/Dublin")
        )
        await session.commit()
    plan_id = await make_plan(t.user_id, TODAY)
    async with make_sessionmaker(db_engine)() as session:
        meals = (
            await session.scalars(
                select(db.PlanMeal)
                .where(db.PlanMeal.plan_id == plan_id, db.PlanMeal.day == 1)
                .options(selectinload(db.PlanMeal.recipe).selectinload(db.Recipe.ingredients))
            )
        ).all()
        meal = min(meals, key=lambda m: SLOT_ORDER.index(Slot(m.slot)))
        line = meal.recipe.ingredients[0]
        assert line.food_id is not None
        food = await session.get(db.Food, line.food_id)
        assert food is not None
        t.recipe_id, t.recipe_name, t.slot = meal.recipe_id, meal.recipe.name, Slot(meal.slot)
        t.food_id, t.food = food.id, food.description
        meal.recipe.instructions = METHOD
        await session.commit()
    return t


async def stock(api: httpx.AsyncClient, auth: Auth, food_id: int, storage: str | None) -> int:
    added = await api.post(
        "/pantry", json={"food_id": food_id, "quantity": 500, "unit": "g"}, headers=auth()
    )
    assert added.status_code == 201, added.text
    item = added.json()["id"]
    kept = await api.patch(f"/pantry/{item}", json={"storage": storage}, headers=auth())
    assert kept.status_code == 200, kept.text
    assert kept.json()["storage"] == (storage or kept.json()["storage"])
    return item


async def rice_id(db_engine: AsyncEngine) -> int:
    async with make_sessionmaker(db_engine)() as session:
        found = await session.scalar(select(db.Food.id).where(db.Food.description.like("Rice,%")))
        assert found is not None
        return found


async def ahead(api: httpx.AsyncClient, auth: Auth, **params: str) -> Any:
    response = await api.get("/plans/ahead", params=params, headers=auth())
    assert response.status_code == 200, response.text
    return response.json()


async def test_tomorrow_lists_food_to_defrost_and_steps_to_start(
    api: httpx.AsyncClient,
    auth: Auth,
    db_engine: AsyncEngine,
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    t = await plan_tomorrow(db_engine, new_user, make_plan)
    item = await stock(api, auth, t.food_id, "freezer")

    out = await ahead(api, auth)

    assert out["date"] == TOMORROW.isoformat()
    meal = {"slot": t.slot.value, "recipe_id": t.recipe_id, "recipe_name": t.recipe_name}
    assert out["items"][0] == {"kind": "defrost", "text": t.food, **meal}
    assert {"kind": "start", "text": "Marinate overnight in the fridge.", **meal} in out["items"]

    # Back to where that food usually is (not the freezer): nothing to defrost.
    await api.patch(f"/pantry/{item}", json={"storage": None}, headers=auth())
    assert [i["kind"] for i in (await ahead(api, auth))["items"]] == ["start"]


async def test_eaten_meals_and_days_off_the_plan_need_nothing(
    api: httpx.AsyncClient,
    auth: Auth,
    db_engine: AsyncEngine,
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    await plan_tomorrow(db_engine, new_user, make_plan)
    async with make_sessionmaker(db_engine)() as session:
        await session.execute(
            update(db.PlanMeal).where(db.PlanMeal.day == 1).values(status="eaten")
        )
        await session.commit()

    assert (await ahead(api, auth))["items"] == []
    assert (await ahead(api, auth, on="2026-12-01"))["items"] == []


async def test_pantry_food_can_be_moved_to_the_freezer_and_back(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser, db_engine: AsyncEngine
) -> None:
    await new_user("user_a")
    rice = await rice_id(db_engine)
    added = await api.post(
        "/pantry", json={"food_id": rice, "quantity": 500, "unit": "g"}, headers=auth()
    )
    item = added.json()["id"]
    usual = added.json()["storage"]

    frozen = await api.patch(f"/pantry/{item}", json={"storage": "freezer"}, headers=auth())
    back = await api.patch(f"/pantry/{item}", json={"storage": None}, headers=auth())
    bad = await api.patch(f"/pantry/{item}", json={"storage": "garage"}, headers=auth())
    quantity_only = await api.patch(f"/pantry/{item}", json={"quantity": 3}, headers=auth())

    assert usual == "cupboard"  # dry rice
    assert frozen.json()["storage"] == "freezer"
    assert back.json()["storage"] == "cupboard"
    assert bad.status_code == 422
    assert quantity_only.json()["storage"] == "cupboard"


def test_the_heads_up_in_one_line() -> None:
    def item(kind: str, text: str, recipe: str = "Chicken curry") -> AheadItemOut:
        return AheadItemOut.model_validate(
            {"kind": kind, "slot": "dinner", "recipe_id": 1, "recipe_name": recipe, "text": text}
        )

    both = ahead_reminder(
        [
            item("defrost", "Chicken, broilers or fryers, meat and skin, raw"),
            item("defrost", "Peas, green, frozen"),
            item("start", "Marinate overnight."),
            item("start", "Chill for 4 hours."),
        ]
    )
    assert both == Reminder(
        "For tomorrow",
        "Take the chicken and peas out of the freezer; start the Chicken curry tonight.",
        url="/plan",
    )
    assert ahead_reminder([]) is None


async def subscribe(db_engine: AsyncEngine, user_id: int) -> None:
    async with make_sessionmaker(db_engine)() as session:
        session.add(
            db.PushSubscription(
                user_id=user_id, endpoint="https://push.example/1", p256dh="p" * 20, auth="a" * 16
            )
        )
        await session.commit()


async def test_the_heads_up_goes_once_an_evening_at_the_users_hour(
    api: httpx.AsyncClient,
    auth: Auth,
    db_engine: AsyncEngine,
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    t = await plan_tomorrow(db_engine, new_user, make_plan)
    await subscribe(db_engine, t.user_id)
    pushed: list[Reminder] = []

    async def push(_: db.PushSubscription, reminder: Reminder) -> None:
        pushed.append(reminder)

    maker = make_sessionmaker(db_engine)
    assert await send_ahead(maker, datetime(2026, 10, 14, 17, tzinfo=UTC), SETTINGS, push) == 0
    assert await send_ahead(maker, SEVEN_PM, SETTINGS, push) == 1
    assert await send_ahead(maker, SEVEN_PM, SETTINGS, push) == 0  # once an evening
    [reminder] = pushed
    assert reminder.body == f"Start the {t.recipe_name} tonight."
    assert reminder.url == "/plan"


async def test_no_heads_up_when_turned_off_or_with_nothing_to_do(
    api: httpx.AsyncClient,
    auth: Auth,
    db_engine: AsyncEngine,
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    t = await plan_tomorrow(db_engine, new_user, make_plan)
    await subscribe(db_engine, t.user_id)
    pushed: list[Reminder] = []

    async def push(_: db.PushSubscription, reminder: Reminder) -> None:
        pushed.append(reminder)

    config = (await api.get("/me/push", headers=auth())).json()
    off = await api.put("/me/push/ahead", json={"enabled": False}, headers=auth())
    maker = make_sessionmaker(db_engine)

    assert config["prep_reminders"] is True
    assert off.status_code == 204
    assert (await api.get("/me/push", headers=auth())).json()["prep_reminders"] is False
    assert await send_ahead(maker, SEVEN_PM, SETTINGS, push) == 0

    # Back on, but tomorrow's meals need nothing ahead.
    await api.put("/me/push/ahead", json={"enabled": True}, headers=auth())
    async with maker() as session:
        await session.execute(update(db.Recipe).values(instructions="Cook and serve."))
        await session.commit()
    assert await send_ahead(maker, SEVEN_PM, SETTINGS, push) == 0
    assert pushed == []
