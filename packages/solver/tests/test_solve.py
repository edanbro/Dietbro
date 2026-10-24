"""The specification for `larder_solver.solve.solve` (the CP-SAT planner).

Any failure here is a bug in the model. The modelling guide is packages/solver/README.md;
the contract is larder_solver.problem (PlanResult explains objective and bound) and
larder_solver.validate is the judge.

Run: `uv run pytest packages/solver/tests/test_solve.py` (functional, about two minutes) and
`uv run pytest -m perf packages/solver` (realistic size, timing).
"""

import math
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from time import perf_counter

import pytest

from larder_solver.metrics import (
    allocate,
    changed_slots,
    cost_millipence,
    day_totals,
    repeat_counts,
    score,
    to_minor,
)
from larder_solver.problem import (
    Allergen,
    Band,
    Food,
    Ingredient,
    Lot,
    Macros,
    Meal,
    Nutrient,
    Plan,
    PlanResult,
    Problem,
    Profile,
    Recipe,
    Slot,
    SlotSpec,
    Status,
    Targets,
    check_problem,
)
from larder_solver.scenarios import (
    DecoyPath,
    forced_churn,
    infeasible,
    planted,
    realistic,
    replan,
    synthetic_catalog,
)
from larder_solver.solve import solve
from larder_solver.validate import hard, validate

B, L, D, S = Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER, Slot.SNACK
START = date(2026, 1, 5)  # a Monday
LIMIT_MS = 2_000  # functional tests: time limit and search workers
WORKERS = 4
FOUND = (Status.OPTIMAL, Status.FEASIBLE)


def run(
    problem: Problem,
    previous: Plan | None = None,
    time_limit_ms: int = LIMIT_MS,
    workers: int = WORKERS,
) -> PlanResult:
    """Call solve() and check what every call must satisfy: planner "cpsat"; a plan exactly
    when the status is OPTIMAL or FEASIBLE; no hard violation in it; objective <= score <=
    bound (PlanResult); wall_ms no more than the time measured around the call."""
    started = perf_counter()
    result = solve(problem, previous, time_limit_ms, workers=workers)
    measured_ms = (perf_counter() - started) * 1000
    assert result.planner == "cpsat"
    assert (result.plan is not None) == (result.status in FOUND), result.status
    assert result.wall_ms <= math.ceil(measured_ms) + 1
    if result.plan is not None:
        assert hard(validate(problem, result.plan)) == []
        assert result.objective is not None
        assert result.bound is not None
        assert result.objective <= score(problem, result.plan, previous).total <= result.bound
    return result


def found(result: PlanResult) -> Plan:
    assert result.status in FOUND, (result.status, result.notes)
    assert result.plan is not None
    return result.plan


# --- 1. planted scenarios ------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(20))
def test_planted_scenarios_get_a_valid_plan(seed: int) -> None:
    """1. Every planted problem (synthetic catalogue, k=10, 7 days) has a valid plan, so
    solve() must return OPTIMAL or FEASIBLE with no hard violations."""
    p = planted(seed, k=10).problem
    assert check_problem(p) == []
    found(run(p))


# --- 2. infeasible -------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(10))
def test_infeasible_scenarios_get_no_plan(seed: int) -> None:
    """2. A daily kcal band beyond reach: INFEASIBLE (UNKNOWN is tolerated), never a plan."""
    result = run(infeasible(seed).problem)
    assert result.status in (Status.INFEASIBLE, Status.UNKNOWN)
    assert result.plan is None


# --- 3. decoys -----------------------------------------------------------------------------------


def test_decoys_are_never_chosen() -> None:
    """3. Decoys are eligible, preference 100 candidates that break one hard filter each
    (food allergen, text-only allergen, text-only animal product, avoided food, unverified
    ingredient, ingredient missing from foods). None may appear in a plan."""
    scenarios = [planted(seed, k=10) for seed in range(12)]
    assert {path for s in scenarios for path in s.decoys.values()} == set(DecoyPath)
    for scenario in scenarios:
        plan = found(run(scenario.problem))
        assert not [m for m in plan.meals if m.recipe_id in scenario.decoys]


# --- 4. locks ------------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_locks_are_honoured(seed: int) -> None:
    """4. A locked Meal appears exactly (recipe and portions); a slot locked to None stays
    empty, even a required one. Here Wednesday's lunch was eaten out (its kcal arrive as
    `extra`), so the planted witness still fits."""
    scenario = planted(seed, k=10)
    witness = scenario.witness
    assert witness is not None
    kept = witness.meals[0]
    out = witness.at(2, L)
    assert out is not None
    eaten = scenario.problem.recipes[out.recipe_id].per_portion.times(out.portions)
    p = replace(
        scenario.problem,
        locked={(kept.day, kept.slot): kept, (2, L): None},
        extra={2: eaten},
    )
    plan = found(run(p))
    assert kept in plan.meals
    assert plan.at(2, L) is None


def test_an_unsafe_lock_makes_the_problem_infeasible() -> None:
    """4. Locks never skip the hard filters: a future meal locked to a recipe that breaks
    the profile means no valid plan exists. Report INFEASIBLE (detecting it before
    searching is fine)."""
    scenario = planted(1, k=10)
    decoy = next(rid for rid in scenario.decoys if D in scenario.problem.recipes[rid].meal_types)
    p = replace(scenario.problem, locked={(4, D): Meal(4, D, decoy, 2)})
    result = run(p)
    assert result.status is Status.INFEASIBLE
    assert result.plan is None


# --- small hand-built problems -------------------------------------------------------------------


def recipe(rid: int, slots: Sequence[Slot], kcal: int, *grams: tuple[int, int]) -> Recipe:
    return Recipe(
        rid,
        f"Recipe {rid}",
        frozenset(slots),
        Macros(kcal, kcal // 20, kcal // 30, kcal // 8),
        tuple(Ingredient(food, g) for food, g in grams),
    )


def problem(
    specs: Sequence[SlotSpec],
    recipes: Sequence[Recipe],
    foods: Sequence[Food],
    *,
    days: int,
    kcal: Band,
    pantry: Sequence[Lot] = (),
    budget: int | None = None,
) -> Problem:
    return Problem(
        start=START,
        days=days,
        slots=tuple(specs),
        recipes={r.id: r for r in recipes},
        foods={f.id: f for f in foods},
        targets=Targets({Nutrient.KCAL: kcal}),
        pantry=tuple(pantry),
        budget=budget,
    )


# --- 5. pantry -----------------------------------------------------------------------------------


def test_pantry_food_is_used_before_it_expires() -> None:
    """5. Two dinners identical except that one uses spinach from the pantry (a lot that
    expires on day 0) and the other kale bought at the same price. OPTIMAL: the spinach
    dinner on day 0, the lot used up, nothing wasted."""
    foods = [Food(1, "rice", price_per_kg=300), Food(2, "spinach", price_per_kg=400)]
    foods.append(Food(3, "kale", price_per_kg=400))
    kale = recipe(1, [D], 700, (1, 100), (3, 50))
    spinach = recipe(2, [D], 700, (1, 100), (2, 50))
    p = problem(
        [SlotSpec(D, True, (1, 2), 2, 2)],
        [kale, spinach],
        foods,
        days=2,
        kcal=Band(1200, 2000),
        pantry=[Lot(2, 100, expires=0)],
    )
    result = run(p, time_limit_ms=10_000)
    plan = found(result)
    assert result.status is Status.OPTIMAL
    assert plan.at(0, D) == Meal(0, D, 2, 2)
    allocation = allocate(p, plan)
    assert allocation.waste == {}
    assert allocation.pantry_used == {2: 100}


# --- 6. budget -----------------------------------------------------------------------------------


def test_budget_is_a_hard_limit() -> None:
    """6. Two dinners identical except price; the dearer one is preferred (preference 100)
    and would avoid a repeat. The budget only covers the cheap one twice, so OPTIMAL is the
    cheap one both days, within budget."""
    foods = [Food(1, "beans", price_per_kg=500), Food(2, "lentils", price_per_kg=750)]
    cheap = recipe(1, [D], 700, (1, 100))
    dear = replace(recipe(2, [D], 700, (2, 100)), preference=100)
    spec = SlotSpec(D, True, (2, 1), 2, 2)
    cheap_only = Plan((Meal(0, D, 1, 2), Meal(1, D, 1, 2)))
    unlimited = problem([spec], [cheap, dear], foods, days=2, kcal=Band(1200, 2000))
    budget = to_minor(cost_millipence(unlimited, allocate(unlimited, cheap_only).buy))
    p = replace(unlimited, budget=budget)
    result = run(p, time_limit_ms=10_000)
    plan = found(result)
    assert result.status is Status.OPTIMAL
    assert cost_millipence(p, allocate(p, plan).buy) <= budget * 1000
    assert {m.recipe_id for m in plan.meals} == {1}


# --- 7. replans ----------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(3))
def test_replanning_an_optimal_plan_changes_nothing(seed: int) -> None:
    """7. Replanning the same problem with previous=the first plan: churn makes every
    change cost w.churn, so an OPTIMAL first plan stays optimal and nothing changes
    (portions aside). Small instance (3 days, k=8), 10 s limit; skipped if the first
    solve isn't OPTIMAL."""
    p = planted(seed, days=3, k=8).problem
    first = run(p, time_limit_ms=10_000)
    if first.status is not Status.OPTIMAL:
        pytest.skip(f"first solve was {first.status}, not OPTIMAL")
    again = run(p, previous=found(first), time_limit_ms=10_000)
    assert again.status is Status.OPTIMAL
    assert changed_slots(found(first), found(again)) == 0


# --- 8. off-plan intake --------------------------------------------------------------------------


def test_extra_counts_toward_the_day() -> None:
    """8. Tuesday's lunch is eaten out: locked to None, 900 kcal in `extra`. The kcal band
    applies to the day's total including extra, so Tuesday's planned meals must come to
    700-1,300 kcal rather than 1,600-2,200."""
    foods = [Food(1, "oats", price_per_kg=200), Food(2, "rice", price_per_kg=300)]
    recipes = [recipe(1 + i, [B], 150 + 50 * i, (1, 60)) for i in range(4)]
    recipes += [recipe(11 + i, [L, D], 250 + 40 * i, (2, 100)) for i in range(8)]
    breakfasts = tuple(r.id for r in recipes if B in r.meal_types)
    mains = tuple(r.id for r in recipes if L in r.meal_types)
    p = problem(
        [
            SlotSpec(B, True, breakfasts, 1, 3, 4),
            SlotSpec(L, True, mains, 1, 4),
            SlotSpec(D, True, mains, 2, 4),
        ],
        recipes,
        foods,
        days=3,
        kcal=Band(1600, 2200),
    )
    p = replace(p, locked={(1, L): None}, extra={1: Macros(900, 30, 30, 100)})
    plan = found(run(p))
    assert plan.at(1, L) is None
    assert 1600 <= day_totals(p, plan)[1].kcal <= 2200


# --- 9. snacks -----------------------------------------------------------------------------------


def test_a_snack_must_earn_its_place() -> None:
    """9. One day, mains fixed inside the kcal band (min == max portions). Snacks fit the
    band but have preference <= 0, cost money and use no pantry: every snack costs
    w.optional_meal plus its price, so OPTIMAL has no snack."""
    foods = [Food(1, "oats", price_per_kg=200), Food(2, "rice", price_per_kg=300)]
    foods.append(Food(3, "apples", price_per_kg=250))
    porridge = recipe(1, [B], 400, (1, 80))
    curry = recipe(2, [L, D], 300, (2, 100))
    stew = recipe(3, [L, D], 350, (2, 100))
    apple = recipe(4, [S], 100, (3, 150))
    flapjack = replace(recipe(5, [S], 180, (1, 40)), preference=-10)
    p = problem(
        [
            SlotSpec(B, True, (1,), 1, 1),
            SlotSpec(L, True, (2,), 2, 2),
            SlotSpec(D, True, (3,), 2, 2),
            SlotSpec(S, False, (4, 5), 1, 2),
        ],
        [porridge, curry, stew, apple, flapjack],
        foods,
        days=1,
        kcal=Band(1500, 2500),  # mains: 400 + 600 + 700 = 1,700
    )
    result = run(p, time_limit_ms=10_000)
    plan = found(result)
    assert result.status is Status.OPTIMAL
    assert plan.at(0, S) is None


# --- 10. objective and bound ---------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_objective_matches_the_score(seed: int) -> None:
    """10. `objective` is the score with every constant included and `bound` an upper bound:
    objective <= score(problem, plan, previous).total <= bound for every plan (checked in
    run() on every call). On small instances solved to OPTIMAL, objective == score exactly:
    the model's objective is a faithful copy of metrics.score."""
    p = planted(seed, days=2, k=4).problem
    result = run(p, time_limit_ms=10_000)
    plan = found(result)
    if result.status is Status.OPTIMAL:
        assert result.objective == score(p, plan).total
    previous = Plan(tuple(m for m in plan.meals if m.day == 0))  # churn on day 1
    again = run(p, previous=previous, time_limit_ms=10_000)
    if again.status is Status.OPTIMAL:
        assert again.objective == score(p, found(again), previous).total


# --- 11. portions and repeat caps ----------------------------------------------------------------


@pytest.mark.parametrize("seed", range(10))
def test_portions_and_repeat_caps_per_slot(seed: int) -> None:
    """11. Unlocked meals use problem.portion_range(slot) (breakfast 1-3, lunch 1-4, dinner
    2-4, snack 1-2 in planted problems) and no recipe appears more than
    problem.repeat_cap(recipe) times (breakfast and snack 4, mains 2)."""
    p = planted(seed, k=10).problem
    plan = found(run(p))
    for meal in plan.meals:
        lo, hi = p.portion_range(meal.slot)
        assert lo <= meal.portions <= hi, meal
    for rid, count in repeat_counts(plan).items():
        assert count <= p.repeat_cap(p.recipes[rid]), rid


# --- 12. wall time -------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(3))
def test_returns_within_the_time_limit(seed: int) -> None:
    """12. solve() returns within time_limit_ms + 500 ms (model building included), at full
    size: 40 candidates per slot, 4 slots, 7 days, a pantry."""
    p = realistic(seed, synthetic_catalog(0)).problem
    started = perf_counter()
    run(p)
    assert (perf_counter() - started) * 1000 <= LIMIT_MS + 500


# --- 13. performance -----------------------------------------------------------------------------


@pytest.mark.perf
def test_realistic_size_p95() -> None:
    """13. Realistic size (synthetic catalogue, k=40, 4 slots, 7 days, pantry), 20 seeds at
    the production limit of 3.5 s and 4 workers: each call <= 4 s wall, nearest-rank p95 <
    4 s. Run with `uv run pytest -m perf packages/solver`."""
    catalog = synthetic_catalog(0)
    walls: list[float] = []
    for seed in range(20):
        p = realistic(seed, catalog).problem
        started = perf_counter()
        run(p, time_limit_ms=3_500)  # the API's plan_workers is 4 too
        walls.append((perf_counter() - started) * 1000)
        assert walls[-1] <= 4_000, (seed, walls[-1])
    walls.sort()
    p95 = walls[math.ceil(0.95 * len(walls)) - 1]
    assert p95 < 4_000, walls


# --- 14. choices (replans) -----------------------------------------------------------------------


def test_choices_are_respected() -> None:
    """14. A chosen cell (`Problem.choices`) holds one of its choice's recipes, at whatever
    portions the slot allows (the planner picks them), even a recipe that isn't one of the
    slot's candidates; the hard filters still apply to the choice. Two days; breakfast and
    lunch sizes fixed, so only dinner portions move. Tuesday's dinner is chosen as recipe 5
    (not a candidate): only 3 portions land the day in 2,100-2,300 kcal. Tuesday's lunch is
    chosen from a peanut dish (preference 100, the profile is peanut-free) or recipe 2. OPTIMAL
    within 10 s."""
    foods = [Food(1, "oats", price_per_kg=200), Food(2, "rice", price_per_kg=300)]
    foods.append(Food(3, "peanuts", allergens=frozenset({Allergen.PEANUTS}), price_per_kg=800))
    porridge = recipe(1, [B], 400, (1, 80))
    curry = recipe(2, [L, D], 300, (2, 100))
    stew = recipe(3, [L, D], 300, (2, 100))
    pie = recipe(4, [L, D], 350, (2, 100))
    special = recipe(5, [L, D], 400, (2, 120))
    satay = replace(recipe(6, [L, D], 300, (2, 80), (3, 30)), preference=100)
    p = problem(
        [
            SlotSpec(B, True, (1,), 1, 1),
            SlotSpec(L, True, (2, 3, 6), 2, 2),
            SlotSpec(D, True, (3, 4, 6), 2, 4),
        ],
        [porridge, curry, stew, pie, special, satay],
        foods,
        days=2,
        kcal=Band(2100, 2300),
    )
    p = replace(
        p,
        profile=Profile(allergens=frozenset({Allergen.PEANUTS})),
        choices={(1, D): (5,), (1, L): (6, 2)},
    )
    assert check_problem(p) == []
    result = run(p, time_limit_ms=10_000)
    plan = found(result)
    assert result.status is Status.OPTIMAL
    assert plan.at(1, D) == Meal(1, D, 5, 3)  # 400 + 600 + 1,200 kcal
    assert plan.at(1, L) == Meal(1, L, 2, 2)


def test_a_chosen_optional_cell_is_planned() -> None:
    """14. A choice makes even an optional slot's meal required: the snack that would never
    earn its place (test 9) is planned on the day it was chosen, and only then."""
    foods = [Food(1, "oats", price_per_kg=200), Food(2, "rice", price_per_kg=300)]
    foods.append(Food(3, "apples", price_per_kg=250))
    porridge = recipe(1, [B], 400, (1, 80))
    curry = recipe(2, [L, D], 300, (2, 100))
    stew = recipe(3, [L, D], 350, (2, 100))
    apple = recipe(4, [S], 100, (3, 150))
    p = problem(
        [
            SlotSpec(B, True, (1,), 1, 1),
            SlotSpec(L, True, (2,), 2, 2),
            SlotSpec(D, True, (3,), 2, 2),
            SlotSpec(S, False, (4,), 1, 2, 7),
        ],
        [porridge, curry, stew, apple],
        foods,
        days=2,
        kcal=Band(1500, 2500),
    )
    p = replace(p, choices={(1, S): (4,)})
    result = run(p, time_limit_ms=10_000)
    plan = found(result)
    assert result.status is Status.OPTIMAL
    assert plan.at(0, S) is None
    assert plan.at(1, S) == Meal(1, S, 4, 1)


# --- 15. day bands (replans) ---------------------------------------------------------------------


def test_day_bands_replace_the_daily_band_and_floor() -> None:
    """15. `Problem.day_kcal` replaces both the daily kcal band and the calorie floor on its
    day; other days keep both. Tuesday's lunch was a 1,800 kcal pizza (locked empty, in
    `extra`), so Tuesday comes to at least 2,450 kcal, over the 2,200 maximum. On Wednesday
    lunch and dinner are skipped, so breakfast alone reaches 900 kcal at most, under the 1,200
    floor. Without day bands there is no plan (INFEASIBLE; UNKNOWN tolerated); with
    Tue Band(1,600, 3,200) and Wed Band(400, 2,200) there is one, and Monday stays within
    1,600-2,200."""
    foods = [Food(1, "oats", price_per_kg=200), Food(2, "rice", price_per_kg=300)]
    recipes = [recipe(1 + i, [B], 150 + 50 * i, (1, 60)) for i in range(4)]
    recipes += [recipe(11 + i, [L, D], 250 + 40 * i, (2, 100)) for i in range(8)]
    breakfasts = tuple(r.id for r in recipes if B in r.meal_types)
    mains = tuple(r.id for r in recipes if L in r.meal_types)
    p = problem(
        [
            SlotSpec(B, True, breakfasts, 1, 3, 4),
            SlotSpec(L, True, mains, 1, 4),
            SlotSpec(D, True, mains, 2, 4),
        ],
        recipes,
        foods,
        days=3,
        kcal=Band(1600, 2200),
    )
    p = replace(
        p,
        locked={(1, L): None, (2, L): None, (2, D): None},
        extra={1: Macros(1800, 60, 70, 200)},
    )
    without = run(p)
    assert without.status in (Status.INFEASIBLE, Status.UNKNOWN)
    assert without.plan is None
    p = replace(p, day_kcal={1: Band(1600, 3200), 2: Band(400, 2200)})
    totals = [t.kcal for t in day_totals(p, found(run(p)))]
    assert 1600 <= totals[0] <= 2200
    assert 1600 <= totals[1] <= 3200
    assert 400 <= totals[2] <= 2200


# --- 16. replan scenarios ------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(10))
def test_replan_scenarios_get_a_valid_plan(seed: int) -> None:
    """16. `scenarios.replan`: a planted problem (k=10) as a mid-week replan, with off-plan
    intake, a skipped dinner, day bands (some under the floor or over the daily maximum) and
    chosen cells, some of whose choices include a decoy. Its witness is valid, so solve() must
    return a plan: every chosen cell holds one of its recipes, no decoy is planned."""
    scenario = replan(seed, k=10)
    p = scenario.problem
    plan = found(run(p))
    for (day, slot), ids in p.choices.items():
        meal = plan.at(day, slot)
        assert meal is not None
        assert meal.recipe_id in ids
    assert not [m for m in plan.meals if m.recipe_id in scenario.decoys]


# --- 17. warm start (replans) --------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(10))
def test_a_replan_is_at_least_as_good_as_keeping_the_plan(seed: int) -> None:
    """17. Warm start: given `previous` (the plan before the change), the replan scores at
    least as well as the witness, which is `previous` minus the cells the change emptied - a
    valid plan that changes nothing it doesn't have to. Hinting every cell from `previous`
    (README section 7) hands CP-SAT that solution at once, so even a FEASIBLE result at the
    time limit can't be worse; and its churn is never below the forced churn."""
    scenario = replan(seed, k=10)
    p, previous, witness = scenario.problem, scenario.previous, scenario.witness
    assert previous is not None
    assert witness is not None
    plan = found(run(p, previous))
    assert score(p, plan, previous).total >= score(p, witness, previous).total
    assert changed_slots(previous, plan) >= forced_churn(scenario)
