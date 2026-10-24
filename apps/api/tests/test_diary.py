"""The food diary (GET /diary) and weigh-ins (/me/weights)."""

from collections.abc import Awaitable, Callable, Coroutine, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.clock import get_clock
from larder_api.main import app
from larder_db.engine import make_sessionmaker
from larder_db.models import BodyProfile, MealLog

Auth = Callable[..., dict[str, str]]
NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]

TODAY = date(2026, 10, 14)


@pytest.fixture(autouse=True)
def clock() -> Iterator[None]:
    app.dependency_overrides[get_clock] = lambda: lambda: datetime(2026, 10, 14, 12, tzinfo=UTC)
    yield
    app.dependency_overrides.pop(get_clock, None)


def _log(user_id: int, on: date, kcal: int, **kw: Any) -> MealLog:
    return MealLog(
        user_id=user_id,
        eaten_on=on,
        slot=kw.get("slot"),
        kind=kw.get("kind", "off_plan"),
        description=kw.get("description", "toast"),
        kcal=kcal,
        protein_g=kw.get("protein_g", 10),
        fat_g=5,
        carbs_g=20,
        source="app",
        voided_at=kw.get("voided_at"),
        items=kw.get("items", []),
    )


async def test_diary_adds_up_each_day_against_the_goal(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser, db_engine: AsyncEngine
) -> None:
    uid = await new_user("user_a", kcal=(1800, 2200))
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            [
                _log(uid, TODAY - timedelta(days=2), 1500),  # under
                _log(uid, TODAY - timedelta(days=1), 1200, slot="lunch"),
                _log(uid, TODAY - timedelta(days=1), 800, slot="dinner"),  # 2000: on target
                _log(uid, TODAY - timedelta(days=1), 900, voided_at=datetime.now(UTC)),
                _log(uid, TODAY, 2500),  # over (today: not counted in the streak yet)
            ]
        )
        await session.commit()

    response = await api.get("/diary", params={"days": 4}, headers=auth())

    assert response.status_code == 200, response.text
    diary = response.json()
    assert diary["today"] == TODAY.isoformat()
    assert [d["date"] for d in diary["days"]] == [
        (TODAY - timedelta(days=n)).isoformat() for n in (3, 2, 1, 0)
    ]
    assert [d["eaten"]["kcal"] for d in diary["days"]] == [0, 1500, 2000, 2500]
    assert [d["status"] for d in diary["days"]] == [None, "under", "on", "over"]
    assert len(diary["days"][2]["logged"]) == 2
    assert (diary["logged_days"], diary["on_target_days"]) == (2, 1)
    assert (diary["kcal_min"], diary["kcal_max"]) == (1800, 2200)


@pytest.mark.usefixtures("menu")
async def test_diary_shows_the_planned_energy(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser, make_plan: MakePlan
) -> None:
    uid = await new_user("user_a")
    await make_plan(uid, TODAY)

    diary = (await api.get("/diary", params={"days": 2}, headers=auth())).json()

    yesterday, today = diary["days"]
    assert yesterday["planned_kcal"] is None  # before the plan
    assert today["planned_kcal"] > 0


async def test_diary_is_per_user(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser, db_engine: AsyncEngine
) -> None:
    await new_user("user_a")
    other = await new_user("user_b")
    async with make_sessionmaker(db_engine)() as session:
        session.add(_log(other, TODAY, 700))
        await session.commit()

    diary = (await api.get("/diary", params={"days": 1}, headers=auth())).json()

    assert diary["days"][0]["eaten"]["kcal"] == 0


async def test_weigh_ins_replace_by_day_and_update_the_profile(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser, db_engine: AsyncEngine
) -> None:
    uid = await new_user("user_a")
    async with make_sessionmaker(db_engine)() as session:
        session.add(
            BodyProfile(
                user_id=uid,
                sex="female",
                birth_year=1990,
                height_cm=170,
                weight_kg=80,
                activity="moderate",
            )
        )
        await session.commit()

    for on, kg in (("2026-10-01", 79.04), ("2026-10-10", 78.5), ("2026-10-10", 78.2)):
        response = await api.put(
            "/me/weights", json={"measured_on": on, "weight_kg": kg}, headers=auth()
        )
        assert response.status_code == 200, response.text

    weights = (await api.get("/me/weights", headers=auth())).json()
    assert weights == [
        {"measured_on": "2026-10-01", "weight_kg": 79.0},
        {"measured_on": "2026-10-10", "weight_kg": 78.2},
    ]
    assert (await api.get("/me/body", headers=auth())).json()["weight_kg"] == 78.2

    gone = await api.delete("/me/weights/2026-10-10", headers=auth())
    assert gone.status_code == 204
    assert (await api.get("/me/body", headers=auth())).json()["weight_kg"] == 79.0
    missing = await api.delete("/me/weights/2026-10-10", headers=auth())
    assert missing.status_code == 404


async def test_weigh_ins_cant_be_in_the_future(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser
) -> None:
    await new_user("user_a")
    response = await api.put(
        "/me/weights", json={"measured_on": "2026-10-20", "weight_kg": 70}, headers=auth()
    )
    assert response.status_code == 400


ONION, OLIVE_OIL = 170000, 171413  # seeded by the `foods` fixture


def _picked(*picks: tuple[int, float]) -> list[dict[str, Any]]:
    return [{"name": "x", "food_id": f, "food": "x", "grams": g} for f, g in picks]


@pytest.mark.usefixtures("foods")
async def test_recent_foods_offer_each_exact_mix_once(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser, db_engine: AsyncEngine
) -> None:
    uid = await new_user("user_a")
    salad = _picked((ONION, 80), (OLIVE_OIL, 10))
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            [
                _log(uid, TODAY - timedelta(days=3), 180, description="onion salad", items=salad),
                _log(uid, TODAY - timedelta(days=1), 180, description="onion salad", items=salad),
                _log(uid, TODAY, 40, description="onion", items=_picked((ONION, 100))),
                _log(uid, TODAY, 850, description="pizza"),  # an estimate: no exact foods
                _log(uid, TODAY, 40, items=_picked((ONION, 50)), voided_at=datetime.now(UTC)),
                _log(uid, TODAY, 40, items=_picked((ONION, 50)), kind="skipped"),
                _log(uid, TODAY - timedelta(days=61), 40, items=_picked((ONION, 20))),
            ]
        )
        await session.commit()

    response = await api.get("/diary/recent", headers=auth())

    assert response.status_code == 200, response.text
    recent = response.json()
    assert [(r["description"], r["last_eaten_on"]) for r in recent] == [
        ("onion", TODAY.isoformat()),
        ("onion salad", (TODAY - timedelta(days=1)).isoformat()),
    ]
    assert [(i["food"]["id"], i["grams"]) for i in recent[1]["items"]] == [
        (ONION, 80),
        (OLIVE_OIL, 10),
    ]
    assert recent[1]["items"][0]["food"]["description"] == "Onions, raw"
    assert (await api.get("/diary/recent", headers=auth("user_b"))).json() == []
