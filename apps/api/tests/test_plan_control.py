"""Plan control from the plan screen: next week's plan beside this week's, swap alternatives and
undo. This week's plan runs Monday 12 to Sunday 18 Oct 2026; it is Wednesday 14 Oct, 12:00 UTC
(chat_support)."""

import uuid
from collections.abc import Awaitable, Callable, Coroutine
from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from chat_support import ChatEnv
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_db import models as db
from larder_db.engine import make_sessionmaker

NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]
MON = date(2026, 10, 12)
WED = MON + timedelta(days=2)
NEXT_MON = MON + timedelta(days=7)


@pytest.fixture
async def plan_id(menu: dict[str, int], new_user: NewUser, make_plan: MakePlan) -> int:
    return await make_plan(await new_user("user_a"), MON)


def meal_at(plan: dict[str, Any], on: date, slot: str) -> dict[str, Any] | None:
    day = next(d for d in plan["days"] if d["date"] == on.isoformat())
    return next((m for m in day["meals"] if m["slot"] == slot), None)


async def replan(api: httpx.AsyncClient, chat: ChatEnv, *changes: dict[str, Any]) -> Any:
    body = {
        "changes": list(changes),
        "client_id": str(uuid.uuid4()),
        "today": WED.isoformat(),
        "local_time": "12:00",
    }
    response = await api.post("/plans/replan", json=body, headers=chat.auth("user_a"))
    assert response.status_code == 200, response.text
    return response.json()


def swap(on: date, slot: str, recipe_id: int | None = None) -> dict[str, Any]:
    change: dict[str, Any] = {"intent": "swap", "when": {"date": on.isoformat(), "slot": slot}}
    if recipe_id is not None:
        change["recipe_id"] = recipe_id
    return change


async def plan_count(engine: AsyncEngine) -> int:
    async with make_sessionmaker(engine)() as session:
        return await session.scalar(select(func.count()).select_from(db.MealPlan)) or 0


# --- next week ----------------------------------------------------------------------------------


async def test_next_weeks_plan_leaves_this_weeks_in_force(
    api: httpx.AsyncClient, chat: ChatEnv, plan_id: int
) -> None:
    auth = chat.auth("user_a")
    created = await api.post("/plans", json={"start": NEXT_MON.isoformat()}, headers=auth)
    assert created.status_code == 201, created.text
    next_id = created.json()["id"]

    current = (await api.get("/plans/current", headers=auth)).json()
    upcoming = (await api.get("/plans/upcoming", headers=auth)).json()
    later = (await api.get("/plans/current", params={"date": "2026-10-20"}, headers=auth)).json()

    assert (current["id"], upcoming["id"], later["id"]) == (plan_id, next_id, next_id)

    # Marking this week's meal eaten and changing this week still act on this week's plan.
    eaten = await api.post(
        f"/plans/{plan_id}/meals/eaten",
        json={"date": WED.isoformat(), "slot": "lunch", "today": WED.isoformat()},
        headers=auth,
    )
    assert eaten.status_code == 200, eaten.text
    outcome = await replan(api, chat, swap(WED, "dinner"))
    assert outcome["results"][0]["status"] == "applied"
    new_version = (await api.get("/plans/current", headers=auth)).json()
    assert new_version["start"] == MON.isoformat()
    assert (await api.get("/plans/upcoming", headers=auth)).json()["id"] == next_id


async def test_no_upcoming_plan_by_default(
    api: httpx.AsyncClient, chat: ChatEnv, plan_id: int
) -> None:
    response = await api.get("/plans/upcoming", headers=chat.auth("user_a"))
    assert response.status_code == 200
    assert response.json() is None


# --- alternatives -------------------------------------------------------------------------------


async def test_alternatives_are_safe_and_new_for_the_day(
    api: httpx.AsyncClient, chat: ChatEnv, plan_id: int
) -> None:
    auth = chat.auth("user_a")
    plan = (await api.get(f"/plans/{plan_id}", headers=auth)).json()

    response = await api.get(
        f"/plans/{plan_id}/alternatives",
        params={"date": WED.isoformat(), "slot": "dinner"},
        headers=auth,
    )

    assert response.status_code == 200, response.text
    options = response.json()
    assert 1 <= len(options) <= 3
    planned_today = {
        m["recipe"]["id"]
        for m in next(d for d in plan["days"] if d["date"] == WED.isoformat())["meals"]
    }
    assert not {o["id"] for o in options} & planned_today
    assert all("dinner" in o["slots"] for o in options)

    # Picking one goes through the ordinary replan.
    outcome = await replan(api, chat, swap(WED, "dinner", options[0]["id"]))
    assert outcome["results"][0]["status"] == "applied"
    now = (await api.get("/plans/current", headers=auth)).json()
    assert meal_at(now, WED, "dinner")["recipe"]["id"] == options[0]["id"]  # type: ignore[index]


async def test_alternatives_for_a_day_outside_the_plan_404(
    api: httpx.AsyncClient, chat: ChatEnv, plan_id: int
) -> None:
    response = await api.get(
        f"/plans/{plan_id}/alternatives",
        params={"date": "2026-11-01", "slot": "dinner"},
        headers=chat.auth("user_a"),
    )
    assert response.status_code == 404


# --- undo -----------------------------------------------------------------------------------


async def test_undo_brings_back_the_previous_version(
    api: httpx.AsyncClient, chat: ChatEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    auth = chat.auth("user_a")
    before = (await api.get(f"/plans/{plan_id}", headers=auth)).json()
    await replan(api, chat, swap(WED, "dinner"))
    changed = (await api.get("/plans/current", headers=auth)).json()
    assert meal_at(changed, WED, "dinner") != meal_at(before, WED, "dinner")

    response = await api.post(f"/plans/{changed['id']}/undo", headers=auth)

    assert response.status_code == 200, response.text
    restored = response.json()
    assert restored["version"] == changed["version"] + 1
    assert [
        [(m["slot"], m["recipe"]["id"], m["portions"]) for m in d["meals"]]
        for d in restored["days"]
    ] == [
        [(m["slot"], m["recipe"]["id"], m["portions"]) for m in d["meals"]] for d in before["days"]
    ]
    assert (await api.get("/plans/current", headers=auth)).json()["id"] == restored["id"]

    # Undoing the undo is not a thing: the restored version's parent is the change itself.
    again = await api.post(f"/plans/{changed['id']}/undo", headers=auth)
    assert again.status_code == 409


async def test_nothing_to_undo_on_a_new_plan(
    api: httpx.AsyncClient, chat: ChatEnv, plan_id: int
) -> None:
    response = await api.post(f"/plans/{plan_id}/undo", headers=chat.auth("user_a"))
    assert response.status_code == 409


async def test_no_undo_after_eating(
    api: httpx.AsyncClient, chat: ChatEnv, plan_id: int, db_engine: AsyncEngine
) -> None:
    auth = chat.auth("user_a")
    await replan(api, chat, swap(WED, "dinner"))
    changed = (await api.get("/plans/current", headers=auth)).json()
    chat.advance(seconds=1)  # the mark is made after the change
    eaten = await api.post(
        f"/plans/{changed['id']}/meals/eaten",
        json={"date": WED.isoformat(), "slot": "lunch", "today": WED.isoformat()},
        headers=auth,
    )
    assert eaten.status_code == 200, eaten.text
    count = await plan_count(db_engine)

    response = await api.post(f"/plans/{changed['id']}/undo", headers=auth)

    assert response.status_code == 409
    assert "can't be undone" in response.json()["detail"][0]
    assert await plan_count(db_engine) == count


async def test_meals_say_what_they_use_from_the_pantry(
    api: httpx.AsyncClient, chat: ChatEnv, plan_id: int
) -> None:
    auth = chat.auth("user_a")
    plan = (await api.get("/plans/current", headers=auth)).json()
    meal = plan["days"][3]["meals"][0]
    recipe = (await api.get(f"/recipes/{meal['recipe']['id']}", headers=auth)).json()
    food = next(i for i in recipe["ingredients"] if i["food_id"])
    assert meal["uses_pantry"] == []

    added = await api.post(
        "/pantry", json={"food_id": food["food_id"], "quantity": 500, "unit": "g"}, headers=auth
    )
    assert added.status_code == 201, added.text
    plan = (await api.get("/plans/current", headers=auth)).json()

    assert plan["days"][3]["meals"][0]["uses_pantry"] == [food["food_name"].split(",")[0]]
