"""Planning a week again: POST /plans with repeat_from (an earlier week) or template_id, saved
templates (/me/templates), and the meals on a date (GET /plans/meals) for copying a day."""

from datetime import date, timedelta
from typing import Any

import httpx
import test_plans
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from test_plans import Auth, set_up, use_planner

from larder_api import planning
from larder_db.engine import make_sessionmaker
from larder_db.models import PlanTemplate, Recipe, User
from larder_solver import PlanResult, Problem, Status

# test_plans' fixtures: its recipe catalogue, and the greedy planner (autouse there and here).
catalog_db = test_plans.catalog_db
overrides = test_plans.overrides

Cells = dict[tuple[int, str], int]


def by_cell(plan: dict[str, Any]) -> Cells:
    return {
        (i, m["slot"]): m["recipe"]["id"] for i, d in enumerate(plan["days"]) for m in d["meals"]
    }


async def recipe_id(db_engine: AsyncEngine, name: str) -> int:
    async with make_sessionmaker(db_engine)() as session:
        found = await session.scalar(select(Recipe.id).where(Recipe.name == name))
        assert found is not None
        return found


async def user_id(db_engine: AsyncEngine, sub: str = "user_a") -> int:
    async with make_sessionmaker(db_engine)() as session:
        found = await session.scalar(select(User.id).where(User.auth_subject == sub))
        assert found is not None
        return found


async def test_repeating_a_week_plans_the_same_meals(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    first = (await api.post("/plans", json={}, headers=auth())).json()
    start = date.fromisoformat(first["start"])

    response = await api.post(
        "/plans",
        json={"start": (start + timedelta(days=7)).isoformat(), "repeat_from": first["start"]},
        headers=auth(),
    )

    assert response.status_code == 201, response.text
    again = response.json()
    assert again["start"] == (start + timedelta(days=7)).isoformat()
    assert by_cell(again) == by_cell(first)
    assert not [n for n in again["notes"] if "Left out" in n]


async def test_nothing_to_repeat_is_404(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    response = await api.post("/plans", json={"repeat_from": "2026-01-05"}, headers=auth())
    assert response.status_code == 404
    assert response.json()["detail"] == ["There's no plan for that week to repeat."]


async def test_a_template_only_brings_back_what_is_still_safe(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth)
    satay = await recipe_id(db_engine, "Satay noodles")
    stew = await recipe_id(db_engine, "Lentil stew")
    chicken = await recipe_id(db_engine, "Chicken and broccoli 0")
    async with make_sessionmaker(db_engine)() as session:
        row = PlanTemplate(
            user_id=await user_id(db_engine),
            name="Old favourites",
            cells=[
                {"day": 0, "slot": "dinner", "recipe_id": satay},
                {"day": 1, "slot": "dinner", "recipe_id": stew},
                {"day": 2, "slot": "dinner", "recipe_id": chicken},
            ],
        )
        session.add(row)
        await session.commit()
        template = row.id
    # Since saving it: a peanut allergy, and "never again" for the stew.
    allergies = {"allergens": ["peanuts"]}
    assert (await api.put("/me/allergies", json=allergies, headers=auth())).status_code == 200
    never = {"verdict": "never"}
    assert (
        await api.put(f"/recipes/{stew}/feedback", json=never, headers=auth())
    ).status_code == 204

    response = await api.post("/plans", json={"template_id": template}, headers=auth())

    assert response.status_code == 201, response.text
    plan = response.json()
    cells = by_cell(plan)
    assert cells[(2, "dinner")] == chicken  # still fine: kept
    assert satay not in cells.values()
    assert stew not in cells.values()
    [note] = [n for n in plan["notes"] if n.startswith("Left out")]
    assert "Satay noodles" in note
    assert "Lentil stew" in note


async def test_meals_that_no_longer_fit_are_planned_fresh(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    await set_up(api, auth)
    first = (await api.post("/plans", json={}, headers=auth())).json()
    real = planning.run_planner

    def picky(problem: Problem) -> PlanResult:
        # As if the repeated meals can't meet the goals any more.
        if problem.choices:
            return PlanResult(status=Status.INFEASIBLE, plan=None, planner="greedy", wall_ms=1)
        return real(problem, None, "greedy", 2000, 1)

    use_planner(picky)
    response = await api.post("/plans", json={"repeat_from": first["start"]}, headers=auth())

    assert response.status_code == 201, response.text
    assert any("planned fresh" in n for n in response.json()["notes"])


async def test_saved_templates_list_rename_and_delete(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    plan = (await api.post("/plans", json={}, headers=auth())).json()

    saved = await api.post(
        "/me/templates", json={"name": " Busy week ", "start": plan["start"]}, headers=auth()
    )
    assert saved.status_code == 201, saved.text
    t = saved.json()
    assert t["name"] == "Busy week"
    assert t["meals"] == sum(len(d["meals"]) for d in plan["days"])
    assert 1 <= len(t["recipes"]) <= 4

    listed = (await api.get("/me/templates", headers=auth())).json()
    assert [x["id"] for x in listed] == [t["id"]]

    renamed = await api.patch(f"/me/templates/{t['id']}", json={"name": "Easy"}, headers=auth())
    assert renamed.json()["name"] == "Easy"

    # Someone else's template: not found, for every use.
    await set_up(api, auth, "user_b")
    assert (await api.delete(f"/me/templates/{t['id']}", headers=auth("user_b"))).status_code == 404
    other = await api.post("/plans", json={"template_id": t["id"]}, headers=auth("user_b"))
    assert other.status_code == 404
    assert (await api.get("/me/templates", headers=auth("user_b"))).json() == []

    from_template = await api.post("/plans", json={"template_id": t["id"]}, headers=auth())
    assert from_template.status_code == 201
    assert by_cell(from_template.json()) == by_cell(plan)

    assert (await api.delete(f"/me/templates/{t['id']}", headers=auth())).status_code == 204
    assert (await api.get("/me/templates", headers=auth())).json() == []


async def test_saving_needs_a_plan_and_has_a_limit(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth)
    missing = await api.post(
        "/me/templates", json={"name": "Nope", "start": "2026-01-05"}, headers=auth()
    )
    assert missing.status_code == 404

    plan = (await api.post("/plans", json={}, headers=auth())).json()
    owner = await user_id(db_engine)
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(PlanTemplate(user_id=owner, name=f"T{i}", cells=[]) for i in range(20))
        await session.commit()
    full = await api.post(
        "/me/templates", json={"name": "One more", "start": plan["start"]}, headers=auth()
    )
    assert full.status_code == 409


async def test_both_sources_at_once_is_refused(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    response = await api.post(
        "/plans", json={"repeat_from": "2026-01-05", "template_id": 1}, headers=auth()
    )
    assert response.status_code == 422


async def test_meals_on_a_date_for_copying_a_day(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    plan = (await api.post("/plans", json={}, headers=auth())).json()
    day = plan["days"][1]

    response = await api.get(f"/plans/meals?on={day['date']}", headers=auth())

    assert response.status_code == 200
    meals = response.json()
    assert [(m["slot"], m["recipe"]["id"]) for m in meals] == [
        (m["slot"], m["recipe"]["id"]) for m in day["meals"]
    ]
    assert meals[0]["recipe"]["name"]
    empty = await api.get("/plans/meals?on=2026-01-05", headers=auth())
    assert empty.json() == []
    other = await api.get(f"/plans/meals?on={day['date']}", headers=auth("user_b"))
    assert other.json() == []
