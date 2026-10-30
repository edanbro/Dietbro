"""Which meals are planned: PUT /me/preferences/meals, and plans that leave a meal to the user
(its share of the day kept free) or skip it."""

from datetime import date
from typing import Any

import httpx
import pytest
import test_plans
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from test_plans import Auth, set_up

from larder_api import planning
from larder_core.meals import Slot, meals_problem, own_shares
from larder_db.engine import make_sessionmaker
from larder_db.models import Allergies, Goals, MealLog, Preferences, User
from larder_solver import Band

# test_plans' fixtures: its recipe catalogue, and the greedy planner (autouse there and here).
catalog_db = test_plans.catalog_db
overrides = test_plans.overrides

MAIN = (Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER)


def modes(breakfast: str = "plan", lunch: str = "plan", dinner: str = "plan") -> dict[Slot, str]:
    return {Slot.BREAKFAST: breakfast, Slot.LUNCH: lunch, Slot.DINNER: dinner, Slot.SNACK: "plan"}


@pytest.mark.parametrize(
    ("chosen", "ok"),
    [
        (modes(), True),
        (modes(breakfast="own", lunch="own"), True),  # just dinners: 40% of the day
        (modes(breakfast="skip"), True),  # two meals, half the day each
        (modes(breakfast="skip", lunch="own"), True),
        (modes(breakfast="own", lunch="own", dinner="own"), False),  # nothing to plan
        (modes(breakfast="skip", lunch="skip"), False),  # the whole day in one dinner
        (modes(breakfast="own", lunch="skip"), False),
    ],
)
def test_meals_problem(chosen: dict[Slot, str], ok: bool) -> None:
    assert (meals_problem(chosen) is None) is ok


def test_own_shares_are_of_the_meals_eaten() -> None:
    assert own_shares(modes(lunch="own")) == {Slot.LUNCH: 0.35}
    assert own_shares(modes(breakfast="skip", lunch="own")) == pytest.approx(
        {Slot.LUNCH: 0.35 / 0.75}
    )


async def put_meals(api: httpx.AsyncClient, auth: Auth, **body: str) -> httpx.Response:
    return await api.put("/me/preferences/meals", json=body, headers=auth())


async def test_meals_are_saved_and_checked(api: httpx.AsyncClient, auth: Auth) -> None:
    before_setup = await put_meals(api, auth, lunch="own")
    await set_up(api, auth)

    saved = await put_meals(api, auth, breakfast="skip", lunch="own", snack="skip")
    again = await api.put("/me/preferences", json={"diet": "pescatarian"}, headers=auth())
    read = (await api.get("/me/preferences", headers=auth())).json()
    refused = await put_meals(api, auth, breakfast="skip", lunch="skip")

    assert before_setup.status_code == 409
    assert saved.status_code == 200, saved.text
    want = {"breakfast": "skip", "lunch": "own", "dinner": "plan", "snack": "skip"}
    assert saved.json()["meals"] == want
    assert again.status_code == 200
    assert read["meals"] == want  # saving the other preferences keeps them
    assert refused.status_code == 400
    assert "over half your day" in refused.json()["detail"][0]
    assert (await put_meals(api, auth, lunch="never")).status_code == 422


def slots_planned(plan: dict[str, Any]) -> set[str]:
    return {m["slot"] for d in plan["days"] for m in d["meals"]}


async def test_an_own_lunch_is_kept_free_and_never_planned(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    await set_up(api, auth)
    assert (await put_meals(api, auth, lunch="own")).status_code == 200

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 201, response.text
    plan = response.json()
    assert "lunch" not in slots_planned(plan)
    assert {"breakfast", "dinner"} <= slots_planned(plan)
    goals = test_plans.GOALS
    kept = round((goals["kcal_min"] + goals["kcal_max"]) / 2 * 0.35)
    assert plan["own_meals"] == [{"slot": "lunch", "kcal": kept}]
    assert plan["skipped_meals"] == []
    # The day's totals count what's kept for lunch, so they still meet the day's band.
    for day in plan["days"]:
        planned = sum(m["nutrition"]["kcal"] for m in day["meals"])
        assert day["totals"]["kcal"] == pytest.approx(planned + kept, abs=1)
        assert day["totals"]["kcal"] >= goals["kcal_min"]


async def test_a_skipped_breakfast_leaves_the_day_to_the_other_meals(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    await set_up(api, auth)
    assert (await put_meals(api, auth, breakfast="skip")).status_code == 200

    plan = (await api.post("/plans", json={}, headers=auth())).json()

    assert "breakfast" not in slots_planned(plan)
    assert plan["skipped_meals"] == ["breakfast"]
    assert plan["own_meals"] == []
    for day in plan["days"]:
        assert day["totals"]["kcal"] >= test_plans.GOALS["kcal_min"]


async def test_food_logged_for_an_own_lunch_replaces_what_was_kept(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth)
    assert (await put_meals(api, auth, lunch="own")).status_code == 200
    start = date.fromisoformat((await api.post("/plans", json={}, headers=auth())).json()["start"])
    async with make_sessionmaker(db_engine)() as session:
        user_id = await session.scalar(select(User.id).where(User.auth_subject == "user_a"))
        assert user_id is not None
        session.add(
            MealLog(
                user_id=user_id,
                eaten_on=start,
                slot="lunch",
                kind="off_plan",
                description="canteen curry",
                kcal=900,
                protein_g=30,
                fat_g=30,
                carbs_g=100,
                source="app",
            )
        )
        await session.commit()

    plan = (await api.post("/plans", json={"start": start.isoformat()}, headers=auth())).json()

    first, second = plan["days"][0], plan["days"][1]
    kept = plan["own_meals"][0]["kcal"]
    planned = [sum(m["nutrition"]["kcal"] for m in d["meals"]) for d in (first, second)]
    assert first["totals"]["kcal"] == pytest.approx(planned[0] + 900, abs=1)  # not + kept
    assert second["totals"]["kcal"] == pytest.approx(planned[1] + kept, abs=1)


async def test_meal_style_is_saved_and_checked(api: httpx.AsyncClient, auth: Auth) -> None:
    body = {"meal_style": "mix"}
    before_setup = await api.put("/me/preferences/meal-style", json=body, headers=auth())
    await set_up(api, auth)

    assert (await api.get("/me/preferences", headers=auth())).json()["meal_style"] == "everyday"
    saved = await api.put("/me/preferences/meal-style", json=body, headers=auth())
    again = await api.put("/me/preferences", json={"diet": "pescatarian"}, headers=auth())
    read = (await api.get("/me/preferences", headers=auth())).json()
    bad = await api.put("/me/preferences/meal-style", json={"meal_style": "odd"}, headers=auth())

    assert before_setup.status_code == 409
    assert saved.status_code == 200, saved.text
    assert saved.json()["meal_style"] == "mix"
    assert again.status_code == 200
    assert read["meal_style"] == "mix"  # saving the other preferences keeps it
    assert bad.status_code == 422


def test_meal_sizes_follow_the_day_and_the_meals_eaten() -> None:
    goals = Goals(kcal_min=1800, kcal_max=2200, calorie_floor=1200)
    allergies = Allergies(allergens=[], avoid_food_ids=[])

    def sizes(**meals: str) -> dict[Slot, Band]:
        prefs = Preferences(meal_modes=meals)
        return planning.meal_sizes(planning.UserInputs(goals, allergies, prefs))

    assert sizes() == {
        Slot.BREAKFAST: Band(325, 675),
        Slot.LUNCH: Band(455, 945),
        Slot.DINNER: Band(520, 1080),
    }
    # With no breakfast the rest of the day gets bigger, and nothing is asked of an "own" lunch.
    skipped = sizes(breakfast="skip", lunch="own")
    assert skipped == {Slot.DINNER: Band(693, 1440)}
