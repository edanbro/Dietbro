"""Household size: goals.household, and plans cooked for everyone. The plan stays the user's
(their goals, their portions); the planner gets a 1/N share of the pantry and the budget, and
shopping, cost, pantry use and what eating a meal takes from the pantry are everyone's."""

from typing import Any

import httpx
import test_plans
from test_plans import APPLE, BROCCOLI, CHICKEN, GOALS, RICE, Auth, set_up, use_planner

from larder_api import planning
from larder_solver import Meal, Plan, PlanResult, Problem, Status, Violation
from larder_solver.validate import Code

# test_plans' fixtures: its recipe catalogue, and the greedy planner (autouse there and here).
catalog_db = test_plans.catalog_db
overrides = test_plans.overrides

BUDGET = 1_000_000  # 10,000.00 a week: never the limit here, and not a multiple of 3


def goals(household: int) -> dict[str, Any]:
    return {**GOALS, "household": household, "weekly_budget_minor": BUDGET}


def lowest_ids(seen: list[Problem]) -> None:
    """A planner that records each problem and fills every required slot with its lowest
    recipe id at the most portions: the same meals whatever the pantry or budget."""

    def plan(problem: Problem) -> PlanResult:
        seen.append(problem)
        meals = tuple(
            Meal(d, spec.slot, min(spec.candidates), problem.portion_range(spec.slot)[1])
            for d in range(problem.days)
            for spec in problem.slots
            if spec.required
        )
        return PlanResult(status=Status.FEASIBLE, plan=Plan(meals), planner="greedy", wall_ms=1)

    use_planner(plan)


async def add_rice(api: httpx.AsyncClient, auth: Auth, grams: int, user: str = "user_a") -> None:
    body = {"food_id": RICE, "quantity": grams, "unit": "g"}
    assert (await api.post("/pantry", json=body, headers=auth(user))).status_code == 201


def grams(shopping: dict[str, Any]) -> dict[int, int]:
    return {i["food_id"]: i["grams"] for i in shopping["items"] if not i["staple"]}


def meals(plan: dict[str, Any]) -> list[tuple[str, str, int, int]]:
    return [
        (d["date"], m["slot"], m["recipe"]["id"], m["portions"])
        for d in plan["days"]
        for m in d["meals"]
    ]


async def test_household_is_saved_with_the_goals(api: httpx.AsyncClient, auth: Auth) -> None:
    await set_up(api, auth)
    alone = (await api.get("/me/goals", headers=auth())).json()

    saved = await api.put("/me/goals", json=goals(4), headers=auth())

    assert alone["household"] == 1  # goals saved without one: just the user
    assert saved.status_code == 200, saved.text
    assert (await api.get("/me/goals", headers=auth())).json()["household"] == 4
    for bad in (0, 9):
        assert (await api.put("/me/goals", json=goals(bad), headers=auth())).status_code == 422


async def test_a_plan_for_three_shops_for_three(api: httpx.AsyncClient, auth: Auth) -> None:
    seen: list[Problem] = []
    lowest_ids(seen)
    await set_up(api, auth, goals=goals(1))
    await add_rice(api, auth, 900)
    one = (await api.post("/plans", json={}, headers=auth())).json()
    one_list = (await api.get(f"/plans/{one['id']}/shopping", headers=auth())).json()

    assert (await api.put("/me/goals", json=goals(3), headers=auth())).status_code == 200
    response = await api.post("/plans", json={"start": one["start"]}, headers=auth())
    three = response.json()
    three_list = (await api.get(f"/plans/{three['id']}/shopping", headers=auth())).json()

    assert response.status_code == 201, response.text
    assert meals(three) == meals(one)  # the plan itself is the user's, as before
    assert three["week_totals"] == one["week_totals"]
    # The planner had one person's share of the pantry and of the budget ...
    [rice_one] = [lot.grams for lot in seen[0].pantry if lot.food_id == RICE]
    [rice_three] = [lot.grams for lot in seen[1].pantry if lot.food_id == RICE]
    assert (rice_one, rice_three) == (900, 300)
    assert (seen[0].budget, seen[1].budget) == (BUDGET, BUDGET // 3)
    # ... and the plan shops for everyone: three times the need, less the whole pantry.
    before, after = grams(one_list), grams(three_list)
    for food in (CHICKEN, BROCCOLI, APPLE):
        if food in before:
            assert after[food] == 3 * before[food]
    assert before[RICE] > 0
    assert after[RICE] + 900 == 3 * (before[RICE] + 900)
    assert three["pantry_used_g"] == 3 * 300
    assert (three["household"], three_list["household"], one["household"]) == (3, 3, 1)
    assert three["budget_minor"] == three_list["budget_minor"] == BUDGET  # exactly, not 3 x 1/3
    assert three["cost_minor"] == three_list["total_minor"]
    assert sum(i["cost_minor"] for i in three_list["items"]) == three_list["total_minor"]


async def test_eating_a_meal_takes_everyones_share(api: httpx.AsyncClient, auth: Auth) -> None:
    lowest_ids([])
    taken: dict[int, float] = {}
    for user, household in (("user_a", 1), ("user_b", 2)):
        await set_up(api, auth, user, goals=goals(household))
        await add_rice(api, auth, 5000, user)
        plan = (await api.post("/plans", json={}, headers=auth(user))).json()
        day = plan["days"][0]["date"]
        body = {"date": day, "slot": "breakfast", "today": day}
        eaten = await api.post(f"/plans/{plan['id']}/meals/eaten", json=body, headers=auth(user))
        assert eaten.status_code == 200, eaten.text
        [rice] = [p for p in eaten.json()["pantry"] if p["food_id"] == RICE]
        taken[household] = rice["grams"]

    assert taken[1] > 0
    assert taken[2] == 2 * taken[1]


def test_an_over_budget_plan_says_so_for_everyone() -> None:
    over = Violation(Code.BUDGET, "Estimated shopping cost 40.00 is over your 33.33 budget")
    home = planning.Household(size=3, budget_minor=10_000)

    assert planning.violation_out(over, household=home, cost_minor=12_000).message == (
        "Estimated shopping cost 120.00 for 3 people is over your 100.00 budget"
    )
    assert planning.violation_out(over).message == over.message  # one person: as written
