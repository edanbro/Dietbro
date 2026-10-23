"""Busy nights: PUT /me/preferences/quick-nights, and POST /plans keeping those dinners quick."""

from datetime import date
from typing import Any

import httpx
import test_plans
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine
from test_plans import Auth, set_up, use_planner

from larder_api import planning
from larder_db.engine import make_sessionmaker
from larder_db.models import Recipe
from larder_solver import PlanResult, Problem, Status

# test_plans' fixtures: its recipe catalogue, and the greedy planner (autouse there and here).
catalog_db = test_plans.catalog_db
overrides = test_plans.overrides

QUICK = {f"Chicken and broccoli {i}" for i in range(4)}


async def time_recipes(db_engine: AsyncEngine) -> None:
    """The first four chicken dinners take 15 minutes; everything else an hour."""
    async with make_sessionmaker(db_engine)() as session:
        await session.execute(update(Recipe).values(minutes=60))
        await session.execute(update(Recipe).where(Recipe.name.in_(QUICK)).values(minutes=15))
        await session.commit()


def dinners(plan: dict[str, Any]) -> dict[str, str]:
    """Each day's dinner: weekday name -> recipe name."""
    return {
        date.fromisoformat(d["date"]).strftime("%a"): m["recipe"]["name"]
        for d in plan["days"]
        for m in d["meals"]
        if m["slot"] == "dinner"
    }


async def quick_nights(api: httpx.AsyncClient, auth: Auth, **body: Any) -> httpx.Response:
    return await api.put("/me/preferences/quick-nights", json=body, headers=auth())


async def test_busy_nights_are_saved_on_their_own(api: httpx.AsyncClient, auth: Auth) -> None:
    before_setup = await quick_nights(api, auth, days=[0], minutes=20)
    await set_up(api, auth)

    saved = await quick_nights(api, auth, days=[4, 0, 0], minutes=20)
    # Saving the other preferences keeps them.
    again = await api.put("/me/preferences", json={"diet": "pescatarian"}, headers=auth())
    read = (await api.get("/me/preferences", headers=auth())).json()

    assert before_setup.status_code == 409
    assert saved.status_code == 200, saved.text
    assert (saved.json()["quick_days"], saved.json()["quick_minutes"]) == ([0, 4], 20)
    assert again.status_code == 200
    assert (read["quick_days"], read["quick_minutes"], read["diet"]) == ([0, 4], 20, "pescatarian")
    for bad in ({"days": [7]}, {"days": [-1]}, {"days": [1], "minutes": 25}):
        assert (await quick_nights(api, auth, **bad)).status_code == 422


async def test_dinner_is_quick_on_busy_nights_only(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth)
    await time_recipes(db_engine)
    start = date.fromisoformat((await api.post("/plans", json={}, headers=auth())).json()["start"])
    # The plan's first, third and fifth days are busy, whatever weekdays those are.
    busy_dates = [date.fromordinal(start.toordinal() + d) for d in (0, 2, 4)]
    busy = {d.strftime("%a"): d.weekday() for d in busy_dates}
    assert (await quick_nights(api, auth, days=list(busy.values()), minutes=20)).status_code == 200

    response = await api.post("/plans", json={"start": start.isoformat()}, headers=auth())

    assert response.status_code == 201, response.text
    plan = response.json()
    by_day = dinners(plan)
    assert {by_day[d] for d in busy} <= QUICK
    assert not [n for n in plan["notes"] if "busy night" in n]


async def test_every_night_busy_still_plans_a_week(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth)
    await time_recipes(db_engine)
    await quick_nights(api, auth, days=list(range(7)), minutes=20)

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 201, response.text
    assert set(dinners(response.json()).values()) <= QUICK


async def test_without_quick_recipes_the_week_is_planned_as_usual(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    await set_up(api, auth)  # no recipe has a time: none is known to be quick
    await quick_nights(api, auth, days=list(range(7)), minutes=20)

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 201, response.text
    assert len(dinners(response.json())) == 7


async def test_quick_dinners_give_way_when_they_cannot_fit(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth)
    await time_recipes(db_engine)
    await quick_nights(api, auth, days=list(range(7)), minutes=20)
    real = planning.run_planner

    def picky(problem: Problem) -> PlanResult:
        # As if the quick dinners can't meet the goals.
        if problem.choices:
            return PlanResult(status=Status.INFEASIBLE, plan=None, planner="greedy", wall_ms=1)
        return real(problem, None, "greedy", 2000, 1)

    use_planner(picky)
    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 201, response.text
    assert any("busy night" in n for n in response.json()["notes"])


async def test_a_repeated_week_keeps_its_meals_over_quick_dinners(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth)
    first = (await api.post("/plans", json={}, headers=auth())).json()
    await time_recipes(db_engine)
    await quick_nights(api, auth, days=list(range(7)), minutes=20)

    response = await api.post("/plans", json={"repeat_from": first["start"]}, headers=auth())

    assert response.status_code == 201, response.text
    assert dinners(response.json()) == dinners(first)
