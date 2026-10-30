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
from larder_api.schemas import MealMode
from larder_core.meals import Slot, meals_problem, own_shares
from larder_db.engine import make_sessionmaker
from larder_db.models import Allergies, Goals, MealLog, Preferences, Recipe, User
from larder_solver import Band, Macros, SlotSpec
from larder_solver import Recipe as Recipe_

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
    want = {
        "breakfast": "skip",
        "lunch": "own",
        "dinner": "plan",
        "morning_snack": "skip",
        "snack": "skip",
        "evening_snack": "skip",
    }
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

    # 2,000 kcal less the afternoon snack's tenth, which is planned by default
    assert sizes() == {
        Slot.BREAKFAST: Band(292, 608),
        Slot.LUNCH: Band(410, 850),
        Slot.DINNER: Band(468, 972),
    }
    # With no breakfast the rest of the day gets bigger, and nothing is asked of an "own" lunch.
    skipped = sizes(breakfast="skip", lunch="own", snack="skip")
    assert skipped == {Slot.DINNER: Band(693, 1440)}
    # More snacks, smaller meals.
    assert sizes(morning_snack="plan", evening_snack="plan")[Slot.DINNER] == Band(364, 756)


async def test_snacks_come_every_day_at_the_times_the_user_chose(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    await set_up(api, auth)
    await put_meals(api, auth, morning_snack="plan", snack="skip", evening_snack="plan")

    plan = (await api.post("/plans", json={}, headers=auth())).json()

    for day in plan["days"]:
        assert [m["slot"] for m in day["meals"]] == [
            "breakfast",
            "morning_snack",
            "lunch",
            "dinner",
            "evening_snack",
        ]
    assert plan["skipped_meals"] == ["snack"]  # the ones nobody asked for aren't "skipped"


async def test_an_own_snack_keeps_room_and_is_never_planned(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    await set_up(api, auth)
    await put_meals(api, auth, snack="own")

    plan = (await api.post("/plans", json={}, headers=auth())).json()

    assert "snack" not in slots_planned(plan)
    assert [o["slot"] for o in plan["own_meals"]] == ["snack"]
    assert plan["own_meals"][0]["kcal"] > 0


@pytest.fixture
async def one_snack(catalog_db: None, db_engine: AsyncEngine) -> None:
    async with make_sessionmaker(db_engine)() as session:
        others = await session.scalars(
            select(Recipe).where(
                Recipe.name.in_(["Apple slices 1", "Apple slices 2", "Apple slices 3"])
            )
        )
        for recipe in others:
            await session.delete(recipe)
        await session.commit()


async def test_one_safe_snack_is_had_every_day_rather_than_refusing_the_week(
    api: httpx.AsyncClient, auth: Auth, one_snack: None
) -> None:
    await set_up(api, auth)

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 201, response.text
    planned = [m["recipe"]["name"] for d in response.json()["days"] for m in d["meals"]]
    assert planned.count("Apple slices 0") == 7

    # Two snacks a day from one recipe is too much to insist on, and still no reason to refuse.
    await put_meals(api, auth, morning_snack="plan")
    response = await api.post("/plans", json={}, headers=auth())
    assert response.status_code == 201, response.text


def snack_spec(slot: Slot, candidates: tuple[int, ...]) -> SlotSpec:
    return SlotSpec(slot, True, candidates)


@pytest.mark.parametrize(
    ("pool", "morning", "afternoon", "cap"),
    [
        (tuple(range(1, 17)), tuple(range(1, 17, 2)), tuple(range(2, 17, 2)), 4),  # dealt
        ((1, 2, 3), (1, 2, 3), (1, 2, 3), 8),  # too few to deal: shared, and the cap rises
        ((1,), (), (), 4),  # one can't fill two a day: nothing to insist on
    ],
)
def test_snacks_are_dealt_between_the_slots(
    pool: tuple[int, ...], morning: tuple[int, ...], afternoon: tuple[int, ...], cap: int
) -> None:
    specs = [snack_spec(s, pool) for s in (Slot.MORNING_SNACK, Slot.SNACK, Slot.EVENING_SNACK)]
    modes: dict[Slot, MealMode] = {
        Slot.MORNING_SNACK: "plan",
        Slot.SNACK: "plan",
        Slot.EVENING_SNACK: "skip",
    }
    # Ids and sizes run the same way here, so the deal goes in id order.
    sizes = {rid: Recipe_(rid, "Snack", frozenset({Slot.SNACK}), Macros(kcal=rid)) for rid in pool}
    options, got = planning._deal_snacks(specs, modes, 7, sizes)  # pyright: ignore[reportPrivateUsage]
    assert options == {Slot.MORNING_SNACK: morning, Slot.SNACK: afternoon}
    assert got == cap


def test_one_safe_snack_a_day_raises_the_cap_to_every_day() -> None:
    specs = [snack_spec(Slot.SNACK, (1,))]
    options, cap = planning._deal_snacks(specs, {Slot.SNACK: "plan"}, 7, {})  # pyright: ignore[reportPrivateUsage]
    assert options == {Slot.SNACK: (1,)}
    assert cap == 7
