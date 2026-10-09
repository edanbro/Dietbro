from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api import planning
from larder_api.main import app
from larder_api.routers.plans import get_catalog_cache, get_planner
from larder_db.engine import make_sessionmaker
from larder_db.models import Food, Goals, MealPlan, Recipe, RecipeIngredient
from larder_solver import Meal, Plan, PlanResult, Problem, Slot, Status

Auth = Callable[..., dict[str, str]]

# Foods with unambiguous tags (no allergens unless named), real FDC ids and categories.
RICE, BROCCOLI, CHICKEN, PEANUTS, APPLE, LENTILS = 169704, 170379, 171477, 172430, 171688, 172421
FOODS = [
    (
        RICE,
        "Rice, white, long-grain, regular, cooked",
        "Cereal Grains and Pasta",
        130,
        2.7,
        0.3,
        28,
    ),
    (BROCCOLI, "Broccoli, raw", "Vegetables and Vegetable Products", 34, 2.8, 0.4, 7),
    (
        CHICKEN,
        "Chicken, broilers or fryers, breast, meat only, raw",
        "Poultry Products",
        120,
        23,
        2.6,
        0,
    ),
    (PEANUTS, "Peanuts, all types, raw", "Legumes and Legume Products", 567, 26, 49, 16),
    (APPLE, "Apples, raw, with skin", "Fruits and Fruit Juices", 52, 0.3, 0.2, 14),
    (
        LENTILS,
        "Lentils, mature seeds, cooked, boiled",
        "Legumes and Legume Products",
        116,
        9,
        0.4,
        20,
    ),
]


def _recipe(
    n: int,
    name: str,
    category: str,
    kcal: float,
    protein: float,
    lines: list[tuple[str, int, float]],
) -> Recipe:
    return Recipe(
        source="test",
        source_id=str(n),
        name=name,
        category=category,
        cuisine="British",
        instructions="Cook and serve.",
        servings=2,
        servings_estimated=False,
        nutrition_complete=True,
        kcal=kcal,
        protein_g=protein,
        fat_g=kcal * 0.3 / 9,
        carbs_g=kcal * 0.5 / 4,
        ingredients=[
            RecipeIngredient(
                position=i,
                raw_name=raw,
                raw_measure=f"{grams}g",
                food_id=food,
                grams=grams,
                match_method="alias",
            )
            for i, (raw, food, grams) in enumerate(lines)
        ],
    )


def _catalog() -> list[Recipe]:
    recipes: list[Recipe] = []
    n = 0
    for i in range(6):
        n += 1
        recipes.append(
            _recipe(n, f"Morning bowl {i}", "Breakfast", 380 + 10 * i, 15, [("rice", RICE, 300)])
        )
    for i in range(10):
        n += 1
        recipes.append(
            _recipe(
                n,
                f"Chicken and broccoli {i}",
                "Chicken",
                600 + 15 * i,
                45,
                [("chicken", CHICKEN, 400), ("broccoli", BROCCOLI, 200), ("rice", RICE, 300)],
            )
        )
    for i in range(4):
        n += 1
        recipes.append(_recipe(n, f"Apple slices {i}", "Snack", 120, 1, [("apple", APPLE, 300)]))
    n += 1
    recipes.append(_recipe(n, "Satay noodles", "Vegetarian", 650, 25, [("peanuts", PEANUTS, 150)]))
    n += 1
    recipes.append(_recipe(n, "Lentil stew", "Vegetarian", 550, 30, [("lentils", LENTILS, 500)]))
    return recipes


@pytest.fixture
async def catalog_db(db_engine: AsyncEngine) -> None:
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            Food(
                id=fid,
                description=d,
                data_type="sr_legacy",
                category=c,
                kcal=k,
                protein_g=p,
                fat_g=f,
                carbs_g=cb,
            )
            for fid, d, c, k, p, f, cb in FOODS
        )
        session.add_all(_catalog())
        await session.commit()


@pytest.fixture(autouse=True)
def overrides(catalog_db: None) -> Iterator[None]:
    cache = planning.CatalogCache()  # per test: each test has its own database contents
    app.dependency_overrides[get_catalog_cache] = lambda: cache
    app.dependency_overrides[get_planner] = lambda: partial(
        planning.run_planner, mode="greedy", time_limit_ms=2000, workers=1
    )
    yield
    app.dependency_overrides.pop(get_catalog_cache, None)
    app.dependency_overrides.pop(get_planner, None)


GOALS: dict[str, Any] = {"kcal_min": 1700, "kcal_max": 2300, "protein_g_min": 90}


async def set_up(
    api: httpx.AsyncClient,
    auth: Auth,
    user: str = "user_a",
    *,
    allergens: list[str] | None = None,
    goals: dict[str, Any] | None = None,
) -> None:
    h = auth(user)
    assert (await api.put("/me/goals", json=goals or GOALS, headers=h)).status_code == 200
    allergies = {"allergens": allergens or []}
    assert (await api.put("/me/allergies", json=allergies, headers=h)).status_code == 200
    assert (await api.put("/me/preferences", json={}, headers=h)).status_code == 200


def use_planner(fake: Callable[[Problem], PlanResult]) -> None:
    app.dependency_overrides[get_planner] = lambda: fake


async def plan_rows(db_engine: AsyncEngine) -> int:
    async with make_sessionmaker(db_engine)() as session:
        return await session.scalar(select(func.count(MealPlan.id))) or 0


async def test_create_plan_fills_every_required_slot(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["planner"] == "greedy"
    assert plan["version"] == 1
    assert len(plan["days"]) == 7
    for day in plan["days"]:
        slots = [m["slot"] for m in day["meals"]]
        assert slots[:3] == ["breakfast", "lunch", "dinner"]
        assert day["totals"]["kcal"] == sum(m["nutrition"]["kcal"] for m in day["meals"])
        assert day["totals"]["kcal"] >= plan["targets"]["calorie_floor"]
    assert plan["excluded_allergens"] == []
    assert plan["shopping_items"] > 0
    assert not [v for v in plan["violations"] if v["code"] in {"allergen", "calorie_floor"}]

    current = await api.get("/plans/current", headers=auth())
    assert current.json()["id"] == plan["id"]


async def test_replanning_adds_a_version(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    first = (await api.post("/plans", json={}, headers=auth())).json()

    second = (await api.post("/plans", json={}, headers=auth())).json()

    assert second["version"] == first["version"] + 1
    assert (await api.get("/plans/current", headers=auth())).json()["id"] == second["id"]


async def test_allergens_are_excluded(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth, allergens=["peanuts"])

    plan = (await api.post("/plans", json={}, headers=auth())).json()

    names = {m["recipe"]["name"] for d in plan["days"] for m in d["meals"]}
    assert "Satay noodles" not in names
    assert plan["excluded_allergens"] == ["peanuts"]


async def test_no_plan_until_setup_is_complete(api: httpx.AsyncClient, auth: Auth) -> None:
    await api.put("/me/goals", json=GOALS, headers=auth())

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 409
    assert any("allergies" in d for d in response.json()["detail"])


async def test_stale_goals_are_sent_back_for_review(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth, goals={"kcal_min": 1200, "kcal_max": 1300})
    body = {"sex": "male", "age": 30, "height_cm": 190, "weight_kg": 110, "activity": "very"}
    assert (await api.put("/me/body", json=body, headers=auth())).status_code == 200

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 409
    assert any("goals" in d for d in response.json()["detail"])


@pytest.mark.parametrize("offset", [-2, 8])
async def test_start_date_must_be_near(api: httpx.AsyncClient, auth: Auth, offset: int) -> None:
    await set_up(api, auth)
    start = datetime.now(UTC).date() + timedelta(days=offset)

    response = await api.post("/plans", json={"start": start.isoformat()}, headers=auth())

    assert response.status_code == 400


def _result(plan: Plan | None, status: Status, planner: str = "greedy") -> PlanResult:
    return PlanResult(status=status, plan=plan, planner=planner, wall_ms=1)


def _first_candidates(problem: Problem, portions: int = 2) -> Plan:
    meals = [
        Meal(d, spec.slot, spec.candidates[0], portions)
        for d in range(problem.days)
        for spec in problem.slots
        if spec.required
    ]
    return Plan(tuple(meals))


async def test_infeasible_explains_why(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    use_planner(lambda p: _result(None, Status.INFEASIBLE))

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 400
    assert response.json()["detail"]


async def test_timeout_is_503(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    use_planner(lambda p: _result(None, Status.UNKNOWN, "cpsat"))

    assert (await api.post("/plans", json={}, headers=auth())).status_code == 503


async def test_a_plan_with_an_allergen_is_never_saved(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    await set_up(api, auth, allergens=["peanuts"])
    # The prefilter drops the peanut recipe; put it back and have a buggy planner pick it.
    real_make = planning.make_problem

    def with_satay(*args: Any, **kwargs: Any) -> Problem:
        problem = real_make(*args, **kwargs)
        catalog: planning.PlanningCatalog = args[1]
        satay = next(r for r in catalog.catalog.recipes.values() if r.name == "Satay noodles")
        return replace(problem, recipes={**problem.recipes, satay.id: satay})

    def unsafe(problem: Problem) -> PlanResult:
        plan = _first_candidates(problem)
        satay = next(r for r in problem.recipes.values() if r.name == "Satay noodles")
        lunch = next(m for m in plan.meals if m.slot == Slot.LUNCH)
        meals = tuple(replace(m, recipe_id=satay.id) if m is lunch else m for m in plan.meals)
        return _result(Plan(meals), Status.FEASIBLE)

    monkeypatch.setattr(planning, "make_problem", with_satay)
    use_planner(unsafe)

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 500
    assert await plan_rows(db_engine) == 0


async def test_a_plan_below_the_calorie_floor_is_refused(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth)
    use_planner(lambda p: _result(_first_candidates(p, portions=1), Status.FEASIBLE))

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 400
    assert any("floor" in d for d in response.json()["detail"])
    assert await plan_rows(db_engine) == 0


async def test_cpsat_plans_with_hard_violations_are_a_bug(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth, goals={"kcal_min": 1700, "kcal_max": 1750})
    # Two servings of everything: above the floor but over the kcal band.
    use_planner(lambda p: _result(_first_candidates(p, portions=4), Status.FEASIBLE, "cpsat"))

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 500
    assert await plan_rows(db_engine) == 0


async def test_current_is_null_without_plans(api: httpx.AsyncClient, auth: Auth) -> None:
    response = await api.get("/plans/current", headers=auth())

    assert response.status_code == 200
    assert response.json() is None


async def test_other_users_plans_are_404(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    plan = (await api.post("/plans", json={}, headers=auth())).json()
    other = auth("user_b")

    assert (await api.get(f"/plans/{plan['id']}", headers=other)).status_code == 404
    assert (await api.get(f"/plans/{plan['id']}/shopping", headers=other)).status_code == 404
    patch = await api.patch(
        f"/plans/{plan['id']}/shopping/{RICE}", json={"checked": True}, headers=other
    )
    assert patch.status_code == 404
    assert (await api.get("/plans/current", headers=other)).json() is None


async def test_shopping_list_lines_add_up_and_tick(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    plan = (await api.post("/plans", json={}, headers=auth())).json()

    shopping = (await api.get(f"/plans/{plan['id']}/shopping", headers=auth())).json()

    to_buy = [i for i in shopping["items"] if not i["staple"]]
    assert sum(i["cost_minor"] for i in to_buy) == shopping["total_minor"] == plan["cost_minor"]
    assert {i["food_id"] for i in to_buy} >= {RICE}
    ticked = await api.patch(
        f"/plans/{plan['id']}/shopping/{RICE}", json={"checked": True}, headers=auth()
    )
    assert ticked.json()["checked"] is True
    again = (await api.get(f"/plans/{plan['id']}/shopping", headers=auth())).json()
    assert next(i for i in again["items"] if i["food_id"] == RICE)["checked"] is True


async def test_recipe_detail_derives_allergens(
    api: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    async with make_sessionmaker(db_engine)() as session:
        recipe_id = await session.scalar(select(Recipe.id).where(Recipe.name == "Satay noodles"))

    detail = (await api.get(f"/recipes/{recipe_id}")).json()

    assert "peanuts" in detail["allergens"]
    assert detail["allergens_complete"] is True
    assert "vegan" in detail["suitable_for"]
    assert detail["per_serving"]["kcal"] == 650
    assert (await api.get("/recipes/999999")).status_code == 404


async def test_export_includes_plans_and_delete_cascades(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth)
    await api.post("/plans", json={}, headers=auth())

    export = (await api.get("/me/export", headers=auth())).json()
    assert len(export["plans"]) == 1
    assert len(export["plans"][0]["meals"]) >= 21

    assert (await api.delete("/me", headers=auth())).status_code == 204
    assert await plan_rows(db_engine) == 0


def test_targets_round_and_widen_daily_macro_bands() -> None:
    goals = _goals(kcal_min=1799.6, kcal_max=2200.4, calorie_floor=1200, protein_g_min=100.4)

    t = planning.targets_from(goals, days=7)

    assert (t.daily[planning.Nutrient.KCAL].min, t.daily[planning.Nutrient.KCAL].max) == (
        1800,
        2200,
    )
    assert t.daily[planning.Nutrient.PROTEIN].min == 80  # 0.8 x 100.4
    assert t.weekly[planning.Nutrient.PROTEIN].min == 703  # 7 x 100.4
    assert planning.Nutrient.FAT not in t.daily
    assert t.calorie_floor == 1200


def test_kcal_band_never_starts_below_the_floor() -> None:
    t = planning.targets_from(_goals(kcal_min=1100, kcal_max=1500, calorie_floor=1300), days=7)
    assert t.daily[planning.Nutrient.KCAL].min == 1300


def _goals(**kw: Any) -> Goals:
    base: dict[str, Any] = {
        "user_id": 1,
        "kcal_min": 1800,
        "kcal_max": 2200,
        "calorie_floor": 1200,
        "max_daily_deficit": 1000,
        "currency": "GBP",
    }
    return Goals(**(base | kw))


def test_plan_seed_is_stable_and_varies() -> None:
    d = date(2026, 10, 12)
    assert planning.plan_seed(1, d, 1) == planning.plan_seed(1, d, 1)
    assert planning.plan_seed(1, d, 1) != planning.plan_seed(1, d, 2)
    assert planning.plan_seed(1, d, 1) != planning.plan_seed(2, d, 1)


def test_portion_grams_rounds_up_and_drops_staples_and_pinches() -> None:
    assert planning.portion_grams(301, servings=2, staple=False) == 76
    assert planning.portion_grams(3, servings=2, staple=False) == 0  # 0.75 g per portion
    assert planning.portion_grams(300, servings=2, staple=True) == 0
    assert planning.portion_grams(None, servings=2, staple=False) == 0


def test_slot_rules_cover_every_slot() -> None:
    assert set(planning.SLOT_RULES) == set(Slot)
