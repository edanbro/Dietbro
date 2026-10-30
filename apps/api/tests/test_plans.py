from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api import planning
from larder_api.main import app
from larder_api.routers.plans import get_catalog_cache, get_planner
from larder_db.engine import make_sessionmaker
from larder_db.models import (
    Food,
    Goals,
    MealLog,
    MealPlan,
    Recipe,
    RecipeIngredient,
    ShoppingItem,
    User,
)
from larder_solver import Band, Macros, Meal, Nutrient, Plan, PlanResult, Problem, Slot, Status
from larder_solver.scenarios import planted

Auth = Callable[..., dict[str, str]]

# Foods with unambiguous tags (no allergens unless named), real FDC ids and categories.
# Ids match the curated aliases, so recipe lines count as exact matches (reviewed tags).
RICE, BROCCOLI, CHICKEN, PEANUTS, APPLE, LENTILS = 168877, 321900, 171447, 2515376, 171688, 172420
FOODS = [
    (
        RICE,
        "Rice, white, long-grain, regular, raw, enriched",
        "Cereal Grains and Pasta",
        130,
        2.7,
        0.3,
        28,
    ),
    (BROCCOLI, "Broccoli, raw", "Vegetables and Vegetable Products", 34, 2.8, 0.4, 7),
    (
        CHICKEN,
        "Chicken, broilers or fryers, meat and skin, raw",
        "Poultry Products",
        120,
        23,
        2.6,
        0,
    ),
    (PEANUTS, "Peanuts, raw", "Legumes and Legume Products", 567, 26, 49, 16),
    (
        APPLE,
        "Apples, raw, with skin (Includes foods for USDA's Food Distribution Program)",
        "Fruits and Fruit Juices",
        52,
        0.3,
        0.2,
        14,
    ),
    (
        LENTILS,
        "Lentils, raw",
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
    recipes.append(_recipe(n, "Satay noodles", "Vegetarian", 650, 25, [("peanut", PEANUTS, 150)]))
    n += 1
    recipes.append(_recipe(n, "Lentil stew", "Vegetarian", 550, 30, [("lentil", LENTILS, 500)]))
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
    def planner(problem: Problem, previous: Plan | None) -> PlanResult:
        assert previous is None  # a new plan replaces nothing
        return fake(problem)

    app.dependency_overrides[get_planner] = lambda: planner


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
        assert slots == ["breakfast", "lunch", "snack", "dinner"]  # eating order
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


async def test_a_new_plan_counts_food_already_logged(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth)
    today = datetime.now(UTC).date()
    async with make_sessionmaker(db_engine)() as session:
        user_id = await session.scalar(select(User.id).where(User.auth_subject == "user_a"))
        assert user_id is not None
        session.add_all(
            [
                MealLog(
                    user_id=user_id,
                    eaten_on=today,
                    slot="lunch",
                    kind="off_plan",
                    description="a burrito",
                    kcal=900,
                    protein_g=40,
                    fat_g=30,
                    carbs_g=110,
                    source="app",
                ),
                MealLog(  # voided: replaced by a later log, never counted
                    user_id=user_id,
                    eaten_on=today,
                    slot="dinner",
                    kind="skipped",
                    description="Skipped",
                    kcal=0,
                    protein_g=0,
                    fat_g=0,
                    carbs_g=0,
                    source="app",
                    voided_at=datetime.now(UTC),
                ),
            ]
        )
        await session.commit()

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 201, response.text
    day = response.json()["days"][0]
    assert [m["slot"] for m in day["meals"]] == ["breakfast", "snack", "dinner"]
    assert [e["description"] for e in day["logged"]] == ["a burrito"]
    assert day["totals"]["kcal"] == sum(m["nutrition"]["kcal"] for m in day["meals"]) + 900


async def test_allergens_are_excluded(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth, allergens=["peanuts"])

    response = await api.post("/plans", json={}, headers=auth())
    assert response.status_code == 201, response.text
    plan = response.json()

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
    body = {"sex": "male", "age": 30, "height_cm": 190, "weight_kg": 110, "activity": "very_active"}
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


def _first_candidates(problem: Problem, portions: int | None = None) -> Plan:
    """The first candidate in every required slot; smallest allowed portions by default."""
    meals = [
        Meal(d, spec.slot, spec.candidates[0], portions or problem.portion_range(spec.slot)[0])
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
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    await set_up(api, auth)
    # A buggy planner that ignores the kcal band; light recipes take it under the floor.
    real_make = planning.make_problem

    def light(*args: Any, **kwargs: Any) -> Problem:
        problem = real_make(*args, **kwargs)
        thin = {i: replace(r, per_portion=Macros(kcal=50)) for i, r in problem.recipes.items()}
        return replace(problem, recipes=thin)

    monkeypatch.setattr(planning, "make_problem", light)
    use_planner(lambda p: _result(_first_candidates(p), Status.FEASIBLE))

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


async def test_shopping_lines_say_which_meals_need_them(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth)
    plan = (await api.post("/plans", json={}, headers=auth())).json()
    on: dict[int, list[str]] = {}
    for day in plan["days"]:
        for meal in day["meals"]:
            on.setdefault(meal["recipe"]["id"], []).append(day["date"])

    shopping = (await api.get(f"/plans/{plan['id']}/shopping", headers=auth())).json()

    async with make_sessionmaker(db_engine)() as session:
        uses = {
            (r, f)
            for r, f in await session.execute(
                select(RecipeIngredient.recipe_id, RecipeIngredient.food_id)
            )
        }
    for item in shopping["items"]:
        assert item["used_in"], item["name"]
        for u in item["used_in"]:
            assert (u["recipe_id"], item["food_id"]) in uses
            assert u["dates"] == sorted(dict.fromkeys(on[u["recipe_id"]]))
        firsts = [u["dates"][0] for u in item["used_in"]]
        assert firsts == sorted(firsts)
    rice = next(i for i in shopping["items"] if i["food_id"] == RICE)
    assert {u["recipe_id"] for u in rice["used_in"]} == {r for r in on if (r, RICE) in uses}


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

    assert (t.daily[Nutrient.KCAL].min, t.daily[Nutrient.KCAL].max) == (
        1800,
        2200,
    )
    assert t.daily[Nutrient.PROTEIN].min == 80  # 0.8 x 100.4
    assert t.weekly[Nutrient.PROTEIN].min == 703  # 7 x 100.4
    assert Nutrient.FAT not in t.daily
    assert t.calorie_floor == 1200


def test_protein_is_capped_at_35_percent_of_calories_unless_the_user_sets_a_max() -> None:
    capped = planning.targets_from(_goals(kcal_max=2300, protein_g_min=88), days=7)
    assert capped.weekly[Nutrient.PROTEIN] == Band(616, 1409)  # 7 x 88; 7 x 2300 x 0.35 / 4
    assert capped.daily[Nutrient.PROTEIN].max == 252  # 1.25 x 201.25

    own = planning.targets_from(_goals(protein_g_min=88, protein_g_max=140), days=7)
    assert own.weekly[Nutrient.PROTEIN].max == 980

    unset = planning.targets_from(_goals(kcal_max=2000), days=7)
    assert unset.weekly[Nutrient.PROTEIN] == Band(None, 1225)

    # A minimum above the cap keeps the band the right way round.
    high = planning.targets_from(_goals(kcal_min=1400, kcal_max=1600, protein_g_min=180), days=7)
    assert high.weekly[Nutrient.PROTEIN] == Band(1260, 1260)


def test_main_meals_are_at_least_a_whole_serving() -> None:
    for slot in (Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER):
        assert planning.SLOT_RULES[slot][1] >= 2, slot  # half-servings


def test_kcal_band_never_starts_below_the_floor() -> None:
    t = planning.targets_from(_goals(kcal_min=1100, kcal_max=1500, calorie_floor=1300), days=7)
    assert t.daily[Nutrient.KCAL].min == 1300


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


async def test_fibre_sugars_sat_fat_and_salt_are_reported(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    async with make_sessionmaker(db_engine)() as session:
        await session.execute(
            update(Recipe).values(fiber_g=4.0, sugars_g=6.0, sat_fat_g=2.0, sodium_mg=400)
        )
        await session.commit()
        recipe_id = await session.scalar(select(Recipe.id).where(Recipe.name == "Satay noodles"))
    await set_up(api, auth)

    plan = (await api.post("/plans", json={}, headers=auth())).json()
    detail = (await api.get(f"/recipes/{recipe_id}")).json()

    assert detail["per_serving"]["salt_g"] == 1.0  # 400 mg sodium x 2.5
    assert plan["targets"]["reference"] == {
        "fiber_g": 30,
        "sugars_g": 90,
        "sat_fat_g": 20,
        "salt_g": 6,
        "iron_mg": 14,
        "calcium_mg": 800,
        "potassium_mg": 2000,
        "vitamin_c_mg": 80,
        "vitamin_d_ug": 5,
        "folate_ug": 200,
        "vitamin_b12_ug": 2.5,
    }
    day = plan["days"][0]
    for meal in day["meals"]:
        assert meal["nutrition"]["fiber_g"] == round(4.0 * meal["servings"], 1)
    assert day["totals"]["fiber_g"] == round(
        sum(m["nutrition"]["fiber_g"] for m in day["meals"]), 1
    )
    assert plan["week_totals"]["salt_g"] == round(
        sum(d["totals"]["salt_g"] or 0 for d in plan["days"]), 1
    )


async def test_lines_sold_in_packs_are_bought_as_whole_packs(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    await set_up(api, auth)
    plan = (await api.post("/plans", json={}, headers=auth())).json()

    shopping = (await api.get(f"/plans/{plan['id']}/shopping", headers=auth())).json()

    rice = next(i for i in shopping["items"] if i["food_id"] == RICE)
    assert rice["pack_g"] == 1000  # a 1 kg bag
    assert rice["packs"] == -(-rice["grams"] // 1000)
    assert rice["till_minor"] >= rice["cost_minor"]
    loose = [i for i in shopping["items"] if i["pack_g"] is None and not i["staple"]]
    assert all(i["till_minor"] == i["cost_minor"] for i in loose)
    assert shopping["till_minor"] == sum(i["till_minor"] for i in shopping["items"])
    assert shopping["till_minor"] >= shopping["total_minor"]


async def test_a_sliver_of_a_pack_is_a_check_not_a_purchase(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    await set_up(api, auth)
    plan = (await api.post("/plans", json={}, headers=auth())).json()
    async with make_sessionmaker(db_engine)() as session:
        await session.execute(
            update(ShoppingItem)
            .where(ShoppingItem.plan_id == plan["id"], ShoppingItem.food_id == RICE)
            .values(grams=10)  # of a 1 kg bag
        )
        await session.commit()

    shopping = (await api.get(f"/plans/{plan['id']}/shopping", headers=auth())).json()

    rice = next(i for i in shopping["items"] if i["food_id"] == RICE)
    assert rice["staple"] is True
    assert rice["pack_g"] is None
    assert rice["till_minor"] == 0
    assert shopping["till_minor"] == sum(i["till_minor"] for i in shopping["items"])


async def test_ticked_lines_move_into_the_pantry_once(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    plan = (await api.post("/plans", json={}, headers=auth())).json()
    shopping = (await api.get(f"/plans/{plan['id']}/shopping", headers=auth())).json()
    rice = next(i for i in shopping["items"] if i["food_id"] == RICE)
    await api.patch(f"/plans/{plan['id']}/shopping/{RICE}", json={"checked": True}, headers=auth())

    moved = await api.post(f"/plans/{plan['id']}/shopping/stock", json={}, headers=auth())
    again = await api.post(f"/plans/{plan['id']}/shopping/stock", json={}, headers=auth())
    pantry = (await api.get("/pantry", headers=auth())).json()
    after = (await api.get(f"/plans/{plan['id']}/shopping", headers=auth())).json()

    assert moved.status_code == 201
    # The whole bag goes in: what the plan doesn't use is there for the next one.
    assert [(i["food"]["id"], i["grams"], i["source"]) for i in moved.json()] == [
        (RICE, rice["packs"] * rice["pack_g"], "shopping")
    ]
    assert again.json() == []  # each line moves once
    assert [i["food"]["id"] for i in pantry] == [RICE]
    assert next(i for i in after["items"] if i["food_id"] == RICE)["stocked"] is True


async def test_named_lines_can_be_moved_without_ticking(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    plan = (await api.post("/plans", json={}, headers=auth())).json()

    moved = await api.post(
        f"/plans/{plan['id']}/shopping/stock", json={"food_ids": [RICE]}, headers=auth()
    )
    other = await api.post(
        f"/plans/{plan['id']}/shopping/stock", json={"food_ids": [RICE]}, headers=auth("user_b")
    )

    assert [i["food"]["id"] for i in moved.json()] == [RICE]
    assert other.status_code == 404


async def test_the_optimiser_plans_a_week_that_breaks_no_hard_rule(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    """The real CP-SAT model end to end (auto mode, as in production, with a short limit): the
    API saves only plans the validator passes, so a 201 from "cpsat" means no hard violation."""
    app.dependency_overrides[get_planner] = lambda: partial(
        planning.run_planner, mode="auto", time_limit_ms=1500, workers=2
    )
    await set_up(api, auth)

    response = await api.post("/plans", json={}, headers=auth())

    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["planner"] == "cpsat"
    assert plan["status"] in ("optimal", "feasible")
    assert not [v for v in plan["violations"] if v["hard"]]


@pytest.mark.parametrize("status", [Status.UNKNOWN, Status.INFEASIBLE])
def test_auto_falls_back_to_the_quick_planner(
    monkeypatch: pytest.MonkeyPatch, status: Status
) -> None:
    """No CP-SAT plan (out of time, or none meets every hard rule): auto saves the baseline's
    plan, noting only when no plan meets every target, and cpsat mode reports the status as it
    is. Which planner made it is never the note: users can't act on that."""
    problem = planted(0, k=10).problem

    def solve(*_: object, **__: object) -> PlanResult:
        return _result(None, status, "cpsat")

    monkeypatch.setattr(planning, "solve", solve)

    auto = planning.run_planner(problem, None, "auto", 1000, 1)
    strict = planning.run_planner(problem, None, "cpsat", 1000, 1)

    assert auto.planner == "greedy"
    assert auto.plan is not None
    closest = [n for n in auto.notes if n == planning.CLOSEST]
    assert closest == ([planning.CLOSEST] if status == Status.INFEASIBLE else [])
    assert not [n for n in auto.notes if "planner" in n]
    assert (strict.status, strict.plan) == (status, None)
