"""Deterministic plan metrics: nutrition totals, pantry allocation, shopping cost, waste and the
objective score. The validator, the baseline planner, the API and the evals all use these, and
`solve()`'s objective must equal `score()` at OPTIMAL (`larder_solver.problem.PlanResult`).

Integer arithmetic throughout, in the units documented in `larder_solver.problem`. Meals with an
unknown recipe or a day outside the horizon, and ingredient foods missing from `problem.foods`,
are skipped rather than raising, so a malformed plan can still be scored and validated (the
validator reports them).

Pantry allocation is earliest-deadline-first (EDF), per food: days in order; within a day, draw
from the lots still usable that day, soonest expiry first (no expiry last, then lot order); buy
the rest. For a fixed plan this uses the most pantry, buys the least and wastes the least.
"""

from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from larder_solver.problem import (
    HARD_NUTRIENTS,
    Lot,
    Macros,
    Meal,
    Plan,
    Problem,
    Recipe,
    Slot,
)


@dataclass(frozen=True, slots=True)
class Allocation:
    """Grams per food id; only non-zero entries."""

    buy: dict[int, int]
    pantry_used: dict[int, int]
    waste: dict[int, int]  # left in lots that expire within the horizon


@dataclass(frozen=True, slots=True)
class Score:
    """`terms` in the order of the `Weights` docstring; `total` is their sum."""

    terms: dict[str, int]
    total: int


def _planned(problem: Problem, plan: Plan) -> Iterator[tuple[Meal, Recipe]]:
    """Meals inside the horizon whose recipe is known."""
    for meal in plan.meals:
        recipe = problem.recipes.get(meal.recipe_id)
        if recipe is not None and 0 <= meal.day < problem.days:
            yield meal, recipe


def day_totals(problem: Problem, plan: Plan) -> list[Macros]:
    """Per day: the planned meals plus `problem.extra` (eaten off-plan)."""
    totals = [problem.extra.get(day, Macros()) for day in range(problem.days)]
    for meal, recipe in _planned(problem, plan):
        totals[meal.day] += recipe.per_portion.times(meal.portions)
    return totals


def week_totals(problem: Problem, plan: Plan) -> Macros:
    """Sum of `day_totals` over the horizon."""
    return sum(day_totals(problem, plan), Macros())


def usage(problem: Problem, plan: Plan) -> dict[int, list[int]]:
    """Grams of each food eaten per day (`days` long). Staples (0 g) use nothing."""
    out: dict[int, list[int]] = {}
    for meal, recipe in _planned(problem, plan):
        for ingredient in recipe.ingredients:
            grams = ingredient.grams * meal.portions
            if grams > 0 and ingredient.food_id in problem.foods:
                out.setdefault(ingredient.food_id, [0] * problem.days)[meal.day] += grams
    return out


def _deadline(lot: Lot, index: int) -> tuple[bool, int, int]:
    return (lot.expires is None, lot.expires or 0, index)


def allocate(problem: Problem, plan: Plan) -> Allocation:
    """Earliest-deadline-first pantry allocation (see the module docstring)."""
    left = [max(lot.grams, 0) for lot in problem.pantry]
    lots: dict[int, list[int]] = {}  # food id -> usable lot indices, soonest expiry first
    for i, lot in sorted(enumerate(problem.pantry), key=lambda il: _deadline(il[1], il[0])):
        if lot.expires is None or lot.expires >= 0:
            lots.setdefault(lot.food_id, []).append(i)

    buy: dict[int, int] = {}
    used: dict[int, int] = {}
    for food_id, per_day in sorted(usage(problem, plan).items()):
        for day, need in enumerate(per_day):
            for i in lots.get(food_id, ()):
                if need == 0:
                    break
                expires = problem.pantry[i].expires
                if expires is not None and expires < day:
                    continue
                take = min(need, left[i])
                if take:
                    left[i] -= take
                    need -= take
                    used[food_id] = used.get(food_id, 0) + take
            if need:
                buy[food_id] = buy.get(food_id, 0) + need

    waste: dict[int, int] = {}
    for i, lot in enumerate(problem.pantry):
        if lot.expires is not None and 0 <= lot.expires < problem.days and left[i]:
            waste[lot.food_id] = waste.get(lot.food_id, 0) + left[i]
    return Allocation(buy, used, waste)


def _priced(problem: Problem, grams: Mapping[int, int]) -> int:
    return sum(g * problem.foods[f].price_per_kg for f, g in grams.items() if f in problem.foods)


def cost_millipence(problem: Problem, buy: Mapping[int, int]) -> int:
    """Shopping cost: grams bought x price per kg, in thousandths of a minor unit."""
    return _priced(problem, buy)


def waste_millipence(problem: Problem, waste: Mapping[int, int]) -> int:
    """Value of the pantry food left to expire, in thousandths of a minor unit."""
    return _priced(problem, waste)


def to_minor(millipence: int) -> int:
    """Millipence -> minor units, rounded up (an estimate never undercounts)."""
    return -(-millipence // 1000)


def repeat_counts(plan: Plan) -> Counter[int]:
    """Meals per recipe id (locked meals included)."""
    return Counter(meal.recipe_id for meal in plan.meals)


def _recipe_by_slot(plan: Plan) -> dict[tuple[int, Slot], int]:
    out: dict[tuple[int, Slot], int] = {}
    for meal in plan.meals:
        out.setdefault((meal.day, meal.slot), meal.recipe_id)  # first meal, like Plan.at
    return out


def changed_slots(previous: Plan | None, plan: Plan) -> int:
    """(day, slot)s whose recipe, or whether there is a meal at all, differs from `previous`.
    Portions alone don't count. 0 without a previous plan."""
    if previous is None:
        return 0
    before, after = _recipe_by_slot(previous), _recipe_by_slot(plan)
    return sum(before.get(key) != after.get(key) for key in before.keys() | after.keys())


def macro_distance(problem: Problem, plan: Plan) -> int:
    """Grams outside the soft (non-kcal) bands: every day's daily bands plus the weekly bands."""
    daily = [(n, b) for n, b in problem.targets.daily.items() if n not in HARD_NUTRIENTS]
    weekly = [(n, b) for n, b in problem.targets.weekly.items() if n not in HARD_NUTRIENTS]
    days = day_totals(problem, plan)
    week = sum(days, Macros())
    return sum(b.distance(t.get(n)) for t in days for n, b in daily) + sum(
        b.distance(week.get(n)) for n, b in weekly
    )


def staples(problem: Problem, plan: Plan) -> set[int]:
    """Foods the plan only ever uses at 0 g: store-cupboard items to check you have."""
    zero: set[int] = set()
    weighed: set[int] = set()
    for _, recipe in _planned(problem, plan):
        for ingredient in recipe.ingredients:
            if ingredient.food_id in problem.foods:
                (weighed if ingredient.grams > 0 else zero).add(ingredient.food_id)
    return zero - weighed


def score(problem: Problem, plan: Plan, previous: Plan | None = None) -> Score:
    """The objective `solve()` maximises (see `Weights`), for any plan, locked meals included."""
    w = problem.weights
    allocation = allocate(problem, plan)
    preference = sum(
        problem.recipes[m.recipe_id].preference
        for m in plan.meals
        if m.recipe_id in problem.recipes
    )
    required = {s.slot for s in problem.slots if s.required}
    terms = {
        "preference": w.preference * preference,
        "pantry": w.pantry * sum(allocation.pantry_used.values()),
        "cost": -w.cost * cost_millipence(problem, allocation.buy),
        "waste": -w.waste * waste_millipence(problem, allocation.waste),
        "repeat": -w.repeat * sum(n - 1 for n in repeat_counts(plan).values()),
        "optional": -w.optional_meal * sum(m.slot not in required for m in plan.meals),
        "macro": -w.macro * macro_distance(problem, plan),
        "churn": -w.churn * changed_slots(previous, plan),
    }
    return Score(terms, sum(terms.values()))
