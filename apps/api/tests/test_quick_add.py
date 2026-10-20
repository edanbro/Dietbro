"""Diary quick-add (POST /diary/log): food the user picked, logged with exact amounts through the
plan-change executor. This week's plan runs Monday 12 to Sunday 18 Oct 2026; it is Wednesday
14 Oct, 12:00 UTC (chat_support)."""

import uuid
from collections.abc import Awaitable, Callable, Coroutine
from datetime import date, timedelta
from typing import Any

import httpx
from chat_support import ChatEnv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from conftest import BROCCOLI, RICE
from larder_db import models as db
from larder_db.engine import make_sessionmaker

NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]
MON = date(2026, 10, 12)
WED = MON + timedelta(days=2)


def body(*items: tuple[int, float], slot: str | None = "dinner", on: date = WED) -> dict[str, Any]:
    return {
        "eaten_on": on.isoformat(),
        "slot": slot,
        "items": [{"food_id": f, "grams": g} for f, g in items],
        "client_id": str(uuid.uuid4()),
        "today": WED.isoformat(),
        "local_time": "12:00",
    }


async def logs(engine: AsyncEngine, user_id: int) -> list[db.MealLog]:
    async with make_sessionmaker(engine)() as session:
        rows = await session.scalars(
            select(db.MealLog).where(db.MealLog.user_id == user_id, db.MealLog.voided_at.is_(None))
        )
        return list(rows)


async def test_logs_exact_food_and_rebalances_the_day(
    api: httpx.AsyncClient,
    chat: ChatEnv,
    db_engine: AsyncEngine,
    menu: dict[str, int],
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    user_id = await new_user("user_a")
    plan_id = await make_plan(user_id, MON)

    response = await api.post(
        "/diary/log", json=body((BROCCOLI, 200), (RICE, 100)), headers=chat.auth("user_a")
    )

    assert response.status_code == 200, response.text
    outcome = response.json()
    assert [r["status"] for r in outcome["results"]] == ["applied"]
    assert outcome["plan_id"] != plan_id  # a new version without the planned dinner
    [log] = await logs(db_engine, user_id)
    assert (log.kind, log.slot, log.eaten_on, log.source) == ("off_plan", "dinner", WED, "app")
    # Broccoli 34 kcal/100 g x 2 + rice 365 kcal/100 g: from the food data, not estimated.
    assert log.kcal == 433
    assert log.estimated is False
    assert [(i["food_id"], i["grams"]) for i in log.items] == [(BROCCOLI, 200), (RICE, 100)]
    assert log.description == "Broccoli, rice"

    diary = await api.get("/diary", headers=chat.auth("user_a"))
    today = next(d for d in diary.json()["days"] if d["date"] == WED.isoformat())
    assert today["eaten"]["kcal"] == 433


async def test_unknown_food_is_refused(
    api: httpx.AsyncClient, chat: ChatEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    response = await api.post(
        "/diary/log", json=body((BROCCOLI, 100), (999_999_999, 50)), headers=chat.auth("user_a")
    )
    assert response.status_code == 404


async def test_amounts_must_be_positive(
    api: httpx.AsyncClient, chat: ChatEnv, menu: dict[str, int], new_user: NewUser
) -> None:
    await new_user("user_a")
    response = await api.post("/diary/log", json=body((BROCCOLI, 0)), headers=chat.auth("user_a"))
    assert response.status_code == 422


async def test_needs_sign_in(api: httpx.AsyncClient) -> None:
    response = await api.post("/diary/log", json=body((BROCCOLI, 100)))
    assert response.status_code == 401
