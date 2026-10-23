"""The weekly recap (GET /insights/recap, larder_api.insights.weekly_recap) and its Sunday push
(larder_api.reminders.send_recaps). It is Wednesday 21 Oct 2026: the last full week is Monday 12
to Sunday 18 October."""

from collections.abc import Awaitable, Callable, Coroutine, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.clock import get_clock
from larder_api.main import app
from larder_api.reminders import Reminder, generate_vapid_keys, recap_reminder, send_recaps
from larder_api.schemas import RecapOut
from larder_api.settings import Settings
from larder_db import models as db
from larder_db.engine import make_sessionmaker

Auth = Callable[..., dict[str, str]]
NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]

ONION = 170000  # seeded by the `foods` fixture
MON, SUN = date(2026, 10, 12), date(2026, 10, 18)
KEYS = generate_vapid_keys()
SETTINGS = Settings.model_validate(
    {"vapid_public_key": KEYS[0], "vapid_private_key": KEYS[1], "recap_hour": 18}
)
# 17:00 UTC is 18:00 in Dublin (Irish summer time until 25 October).
SUNDAY_SIX_PM = datetime(2026, 10, 18, 17, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clock() -> Iterator[None]:
    app.dependency_overrides[get_clock] = lambda: lambda: datetime(2026, 10, 21, 12, tzinfo=UTC)
    yield
    app.dependency_overrides.pop(get_clock, None)


def log(user_id: int, on: date, kind: str, kcal: int, recipe_id: int | None = None) -> db.MealLog:
    return db.MealLog(
        user_id=user_id,
        eaten_on=on,
        slot="dinner" if kind != "off_plan" else None,
        kind=kind,
        description=kind,
        kcal=kcal,
        protein_g=40,
        fat_g=10,
        carbs_g=50,
        estimated=False,
        source="app",
        recipe_id=recipe_id,
    )


async def seed_week(
    engine: AsyncEngine, user_id: int, menu: dict[str, int], make_plan: MakePlan
) -> None:
    await make_plan(user_id, MON)
    stew = menu["Lentil stew"]
    async with make_sessionmaker(engine)() as session:
        session.add_all(
            [
                log(user_id, MON, "eaten", 1900, stew),
                log(user_id, MON + timedelta(days=1), "eaten", 2000, stew),
                log(user_id, MON + timedelta(days=2), "eaten", 2600),
                log(user_id, MON + timedelta(days=2), "skipped", 0),
                log(user_id, MON + timedelta(days=3), "off_plan", 1800),
                log(user_id, MON - timedelta(days=1), "eaten", 9999),  # the week before
                db.BodyWeight(user_id=user_id, measured_on=MON, weight_kg=80.0),
                db.BodyWeight(user_id=user_id, measured_on=SUN, weight_kg=79.4),
                db.ReceiptUpload(
                    user_id=user_id,
                    source="text",
                    status="confirmed",
                    purchased_on=MON + timedelta(days=5),
                    lines=[
                        db.ReceiptLine(
                            position=0,
                            raw_text="ONIONS",
                            name="onions",
                            food_id=ONION,
                            grams=500,
                            price_minor=6240,
                            status="accepted",
                        )
                    ],
                ),
            ]
        )
        await session.commit()


@pytest.mark.usefixtures("foods")
async def test_the_last_full_week_in_review(
    api: httpx.AsyncClient,
    auth: Auth,
    new_user: NewUser,
    menu: dict[str, int],
    make_plan: MakePlan,
    db_engine: AsyncEngine,
) -> None:
    uid = await new_user("user_a", kcal=(1800, 2400), budget=7000)
    await seed_week(db_engine, uid, menu, make_plan)
    await new_user("user_b")

    response = await api.get("/insights/recap", headers=auth("user_a"))

    assert response.status_code == 200, response.text
    r = response.json()
    assert (r["week_start"], r["week_end"]) == ("2026-10-12", "2026-10-18")
    assert r["planned_meals"] >= 21  # breakfast, lunch and dinner every day
    assert (r["eaten_meals"], r["skipped_meals"], r["off_plan"]) == (3, 1, 1)
    assert r["logged_days"] == 4
    assert r["avg_kcal"] == round((1900 + 2000 + 2600 + 1800) / 4)
    assert r["on_target_days"] == 3  # 2600 is over 2400
    assert r["protein_days"] == 0  # 40 g a log; the goal is 90 g
    assert (r["spent_minor"], r["budget_minor"]) == (6240, 7000)
    assert r["weight_change_kg"] == -0.6
    assert r["top_recipes"][0]["recipe"]["name"] == "Lentil stew"
    assert r["top_recipes"][0]["times"] == 2
    assert r["empty"] is False

    other = (await api.get("/insights/recap", headers=auth("user_b"))).json()
    assert other["empty"] is True
    assert other["eaten_meals"] == 0


async def test_any_day_picks_its_week_but_not_a_future_one(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser
) -> None:
    await new_user("user_a")
    this_week = await api.get("/insights/recap?week=2026-10-21", headers=auth("user_a"))
    assert this_week.json()["week_start"] == "2026-10-19"
    future = await api.get("/insights/recap?week=2026-10-26", headers=auth("user_a"))
    assert future.status_code == 400


def recap(**overrides: Any) -> RecapOut:
    base: dict[str, Any] = {
        "week_start": MON,
        "week_end": SUN,
        "currency": "EUR",
        "planned_meals": 21,
        "eaten_meals": 15,
        "skipped_meals": 1,
        "off_plan": 2,
        "logged_days": 6,
        "avg_kcal": 2050,
        "kcal_min": 1800,
        "kcal_max": 2300,
        "on_target_days": 5,
        "protein_g_min": 90,
        "protein_days": 4,
        "spent_minor": 6240,
        "budget_minor": 7000,
        "planned_cost_minor": 6685,
        "weight_change_kg": -0.6,
        "weight_kg": 79.4,
        "top_recipes": [],
        "price_rises": [],
        "empty": False,
    }
    return RecapOut.model_validate(base | overrides)


def test_the_recap_in_one_line() -> None:
    reminder = recap_reminder(recap())
    assert reminder is not None
    assert reminder.title == "Your week in review"
    assert reminder.body == (
        "15 of 21 planned meals eaten, €62.40 spent of €70.00, weight -0.6 kg. Tap to see it."
    )
    assert reminder.url == "/recap?week=2026-10-12"
    no_plan = recap_reminder(recap(planned_meals=0, budget_minor=None, weight_change_kg=None))
    assert no_plan is not None
    assert no_plan.body == "6 days logged, €62.40 spent. Tap to see it."
    assert recap_reminder(recap(empty=True)) is None


async def subscriber(engine: AsyncEngine, new_user: NewUser, sub: str = "user_a") -> int:
    uid = await new_user(sub)
    async with make_sessionmaker(engine)() as session:
        await session.execute(
            update(db.User).where(db.User.id == uid).values(timezone="Europe/Dublin")
        )
        session.add(
            db.PushSubscription(
                user_id=uid,
                endpoint=f"https://push.example/{sub}",
                p256dh="p" * 20,
                auth="a" * 16,
            )
        )
        await session.commit()
    return uid


@pytest.mark.usefixtures("foods")
async def test_the_recap_goes_out_on_sunday_evening_once(
    db_engine: AsyncEngine, new_user: NewUser, menu: dict[str, int], make_plan: MakePlan
) -> None:
    uid = await subscriber(db_engine, new_user)
    await seed_week(db_engine, uid, menu, make_plan)
    pushed: list[Reminder] = []

    async def push(_: db.PushSubscription, reminder: Reminder) -> None:
        pushed.append(reminder)

    maker = make_sessionmaker(db_engine)
    saturday = SUNDAY_SIX_PM - timedelta(days=1)
    assert await send_recaps(maker, saturday, SETTINGS, push) == 0
    assert await send_recaps(maker, SUNDAY_SIX_PM - timedelta(hours=1), SETTINGS, push) == 0
    assert await send_recaps(maker, SUNDAY_SIX_PM, SETTINGS, push) == 1
    assert await send_recaps(maker, SUNDAY_SIX_PM, SETTINGS, push) == 0  # once a Sunday
    [reminder] = pushed
    assert reminder.url == "/recap?week=2026-10-12"
    assert reminder.body.startswith("3 of ")


async def test_no_recap_when_turned_off_or_for_an_empty_week(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine, new_user: NewUser
) -> None:
    await subscriber(db_engine, new_user)  # nothing logged, bought or weighed
    pushed: list[Reminder] = []

    async def push(_: db.PushSubscription, reminder: Reminder) -> None:
        pushed.append(reminder)

    maker = make_sessionmaker(db_engine)
    assert await send_recaps(maker, SUNDAY_SIX_PM, SETTINGS, push) == 0
    async with maker() as session:
        sub = await session.scalar(select(db.PushSubscription))
        assert sub is not None
        assert sub.recap_sent_on == SUN  # checked: not again today

    off = await api.put("/me/push/recap", json={"enabled": False}, headers=auth("user_a"))
    assert off.status_code == 204
    assert (await api.get("/me/push", headers=auth("user_a"))).json()["weekly_recap"] is False
    async with maker() as session:
        await session.execute(update(db.PushSubscription).values(recap_sent_on=None))
        await session.commit()
    assert await send_recaps(maker, SUNDAY_SIX_PM, SETTINGS, push) == 0
    assert pushed == []
