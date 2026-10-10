"""Independent plan validator (PLAN §6): checks any plan against every rule of the contract and
says in plain English what is wrong. Tests, evals and the API (a runtime assertion before a plan
is saved) all use it, whichever planner made the plan: the planner never grades itself.

Independence is deliberate. The hard filters (allergens, avoided foods, diet, unverified recipes,
unknown foods) are written again here rather than shared with the candidate prefilter, and this
module imports only `larder_solver.problem` and `larder_solver.metrics` (a test enforces it).
Malformed plans (unknown recipes, slots or days) are reported, never raised.

Every violation is hard except the protein/fat/carbs bands, which are soft (missing them costs
`Weights.macro` per gram). `SAFETY_CODES` must never reach a user; `STRUCTURAL_CODES` mean the
planner itself is broken.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from larder_core.tagging import FORBIDDEN
from larder_solver.metrics import allocate, cost_millipence, day_totals, repeat_counts, to_minor
from larder_solver.problem import (
    HARD_NUTRIENTS,
    SLOT_ORDER,
    Allergen,
    AnimalTag,
    Band,
    Macros,
    Meal,
    Nutrient,
    Plan,
    Problem,
    Recipe,
    Slot,
)


class Code(StrEnum):
    """Violation kinds, in reporting order within a (day, slot)."""

    DAY_RANGE = "day_range"
    UNKNOWN_SLOT = "unknown_slot"
    DUPLICATE = "duplicate"
    MISSING = "missing"
    UNKNOWN_RECIPE = "unknown_recipe"
    NOT_ELIGIBLE = "not_eligible"
    PORTIONS = "portions"
    ALLERGEN = "allergen"
    UNVERIFIED = "unverified"
    AVOIDED = "avoided"
    DIET = "diet"
    UNKNOWN_FOOD = "unknown_food"
    LOCKED = "locked"
    REPEATS = "repeats"
    CALORIE_FLOOR = "calorie_floor"
    DAILY_BAND = "daily_band"
    WEEKLY_BAND = "weekly_band"
    BUDGET = "budget"


# The per-meal rules every meal must pass, locked or not.
HARD_FILTER_CODES = frozenset(
    {Code.ALLERGEN, Code.UNVERIFIED, Code.AVOIDED, Code.DIET, Code.UNKNOWN_FOOD}
)
# Could hurt someone: a plan with any of these is never shown, whichever planner made it.
SAFETY_CODES = HARD_FILTER_CODES | {Code.CALORIE_FLOOR}
# The plan doesn't fit the problem's shape: a planner bug.
STRUCTURAL_CODES = frozenset(
    {
        Code.DAY_RANGE,
        Code.UNKNOWN_SLOT,
        Code.DUPLICATE,
        Code.MISSING,
        Code.UNKNOWN_RECIPE,
        Code.NOT_ELIGIBLE,
        Code.PORTIONS,
        Code.LOCKED,
    }
)


@dataclass(frozen=True, slots=True)
class Violation:
    code: Code
    message: str
    hard: bool = True
    day: int | None = None  # None: about the whole plan
    slot: Slot | None = None  # None: about the whole day (or plan)
    recipe_id: int | None = None


def validate(problem: Problem, plan: Plan) -> list[Violation]:
    """Every rule `plan` breaks ([] = valid): one violation per (code, day, slot, recipe or
    nutrient), ordered by day (plan-wide last), slot (`SLOT_ORDER`, day-wide after) and code."""
    found = [
        *_meals(problem, plan),
        *_slots(problem, plan),
        *_nutrition(problem, plan),
        *_repeats(problem, plan),
        *_budget(problem, plan),
    ]
    return sorted(dict.fromkeys(found), key=_order)


def hard(violations: Iterable[Violation]) -> list[Violation]:
    return [v for v in violations if v.hard]


_CODE_RANK = {code: i for i, code in enumerate(Code)}
_SLOT_RANK = {slot: i for i, slot in enumerate(SLOT_ORDER)}


def _order(v: Violation) -> tuple[bool, int, int, int]:
    slot = len(SLOT_ORDER) if v.slot is None else _SLOT_RANK.get(v.slot, len(SLOT_ORDER))
    return (v.day is None, v.day or 0, slot, _CODE_RANK[v.code])


# --- per meal ------------------------------------------------------------------------------------


def _is_locked(problem: Problem, meal: Meal) -> bool:
    return problem.locked.get((meal.day, meal.slot)) == meal


def _at(code: Code, meal: Meal, message: str) -> Violation:
    return Violation(code, message, day=meal.day, slot=meal.slot, recipe_id=meal.recipe_id)


def _meals(problem: Problem, plan: Plan) -> Iterator[Violation]:
    planned = {s.slot for s in problem.slots}
    seen: set[tuple[int, Slot]] = set()
    for meal in plan.meals:
        recipe = problem.recipes.get(meal.recipe_id)
        name = recipe.name if recipe else f"recipe {meal.recipe_id}"
        where = f"{_day(problem, meal.day)} {meal.slot}"
        if not 0 <= meal.day < problem.days:
            yield _at(
                Code.DAY_RANGE, meal, f"{where}: {name} is outside this {problem.days}-day plan"
            )
        if meal.slot not in planned:
            yield _at(
                Code.UNKNOWN_SLOT, meal, f"{where}: {name} is in a slot this plan doesn't have"
            )
        if (meal.day, meal.slot) in seen:
            yield _at(Code.DUPLICATE, meal, f"{where}: {name} is a second meal in one slot")
        seen.add((meal.day, meal.slot))
        if recipe is None:
            yield _at(Code.UNKNOWN_RECIPE, meal, f"{where}: unknown recipe {meal.recipe_id}")
            continue
        if meal.slot in planned and not _is_locked(problem, meal):
            if meal.slot not in recipe.meal_types:
                yield _at(Code.NOT_ELIGIBLE, meal, f"{where}: {name} isn't a {meal.slot} recipe")
            lo, hi = problem.portion_range(meal.slot)
            if not lo <= meal.portions <= hi:
                yield _at(
                    Code.PORTIONS,
                    meal,
                    f"{where}: {meal.portions} portions of {name}; allowed {lo} to {hi}",
                )
        yield from _hard_filters(problem, meal, recipe, f"{where}: {name}")


def _hard_filters(problem: Problem, meal: Meal, recipe: Recipe, what: str) -> Iterator[Violation]:
    """§2.2 of the planning contract, for one meal; re-implemented, not shared (see above)."""
    profile = problem.profile
    known = [problem.foods[i.food_id] for i in recipe.ingredients if i.food_id in problem.foods]
    allergens = recipe.text_allergens.union(*(f.allergens for f in known))
    if hit := allergens & profile.allergens:
        names = [str(a).replace("_", " ") for a in sorted(hit, key=_allergen_rank)]
        yield _at(Code.ALLERGEN, meal, f"{what} contains {_join(names)}")
    if recipe.unresolved > 0 and profile.restricted:
        lines = "1 ingredient" if recipe.unresolved == 1 else f"{recipe.unresolved} ingredients"
        yield _at(
            Code.UNVERIFIED,
            meal,
            f"{what} has {lines} we couldn't check against your allergies and diet",
        )
    avoided = _unique(i.food_id for i in recipe.ingredients if i.food_id in profile.avoid_food_ids)
    if avoided:
        names = [problem.foods[f].name if f in problem.foods else "a food" for f in avoided]
        yield _at(Code.AVOIDED, meal, f"{what} contains {_join(names)}, which you avoid")
    if profile.diet is not None:
        animal = recipe.text_animal.union(*(f.animal for f in known))
        if bad := animal & FORBIDDEN[profile.diet]:
            tags = _join([str(t) for t in AnimalTag if t in bad])
            yield _at(Code.DIET, meal, f"{what} isn't {profile.diet} ({tags})")
    missing = _unique(i.food_id for i in recipe.ingredients if i.food_id not in problem.foods)
    if missing:
        ids = ", ".join(map(str, missing))
        yield _at(Code.UNKNOWN_FOOD, meal, f"{what} uses an ingredient we have no data for ({ids})")


# --- per slot, day and plan ----------------------------------------------------------------------


def _slots(problem: Problem, plan: Plan) -> Iterator[Violation]:
    at: dict[tuple[int, Slot], list[Meal]] = {}
    for meal in plan.meals:
        at.setdefault((meal.day, meal.slot), []).append(meal)
    for day in range(problem.days):
        for spec in problem.slots:
            key = (day, spec.slot)
            if spec.required and key not in at and key not in problem.locked:
                where = f"{_day(problem, day)} {spec.slot}"
                yield Violation(Code.MISSING, f"{where}: no meal planned", day=day, slot=spec.slot)
    for (day, slot), lock in problem.locked.items():
        meals = at.get((day, slot), [])
        where = f"{_day(problem, day)} {slot}"
        if lock is None and meals:
            rid = meals[0].recipe_id
            message = f"{where}: should stay empty, but {_name(problem, rid)} is planned"
            yield Violation(Code.LOCKED, message, day=day, slot=slot, recipe_id=rid)
        elif lock is not None and lock not in meals:
            rid = lock.recipe_id
            message = f"{where}: should be {lock.portions} portions of {_name(problem, rid)}"
            yield Violation(Code.LOCKED, message, day=day, slot=slot, recipe_id=rid)


def _nutrition(problem: Problem, plan: Plan) -> Iterator[Violation]:
    totals = day_totals(problem, plan)
    floor = problem.targets.calorie_floor
    for day, total in enumerate(totals):
        label = _day(problem, day)
        if total.kcal < floor:
            message = f"{label}: {total.kcal:,} kcal is below your {floor:,} kcal floor"
            yield Violation(Code.CALORIE_FLOOR, message, day=day)
        yield from _bands(Code.DAILY_BAND, label, problem.targets.daily, total, day)
    label = "This week" if problem.days == 7 else "Whole plan"
    yield from _bands(Code.WEEKLY_BAND, label, problem.targets.weekly, sum(totals, Macros()), None)


_UNIT = {
    Nutrient.KCAL: ("kcal", ""),
    Nutrient.PROTEIN: ("g", " protein"),
    Nutrient.FAT: ("g", " fat"),
    Nutrient.CARBS: ("g", " carbs"),
}


def _bands(
    code: Code, label: str, bands: Mapping[Nutrient, Band], total: Macros, day: int | None
) -> Iterator[Violation]:
    for nutrient in Nutrient:
        band = bands.get(nutrient)
        value = total.get(nutrient)
        if band is None or band.contains(value):
            continue
        unit, what = _UNIT[nutrient]
        if band.min is not None and value < band.min:
            limit, side, word = band.min, "minimum", "below"
        else:
            limit, side, word = band.max, "maximum", "above"
        message = f"{label}: {value:,} {unit}{what} is {word} your {limit:,} {unit} {side}"
        yield Violation(code, message, hard=nutrient in HARD_NUTRIENTS, day=day)


def _repeats(problem: Problem, plan: Plan) -> Iterator[Violation]:
    counts = repeat_counts(plan)
    for rid in sorted(counts):
        recipe = problem.recipes.get(rid)
        if recipe is None:
            continue
        cap = problem.repeat_cap(recipe)
        unlocked = any(m.recipe_id == rid and not _is_locked(problem, m) for m in plan.meals)
        if counts[rid] > cap and unlocked:
            message = f"{recipe.name} is planned {counts[rid]} times; the limit is {cap}"
            yield Violation(Code.REPEATS, message, recipe_id=rid)


def _budget(problem: Problem, plan: Plan) -> Iterator[Violation]:
    if problem.budget is None:
        return
    cost = cost_millipence(problem, allocate(problem, plan).buy)
    if cost > problem.budget * 1000:
        yield Violation(
            Code.BUDGET,
            f"Estimated shopping cost {_money(to_minor(cost))} is over your "
            f"{_money(problem.budget)} budget",
        )


# --- wording -------------------------------------------------------------------------------------

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _day(problem: Problem, day: int) -> str:
    """'Tue' (with the date on plans longer than a week); 'Day 9' outside the plan."""
    if not 0 <= day < problem.days:
        return f"Day {day}"
    d = problem.start + timedelta(days=day)
    name = _WEEKDAYS[d.weekday()]
    return name if problem.days <= 7 else f"{name} {d.day} {_MONTHS[d.month - 1]}"


_ALLERGEN_RANK = {a: i for i, a in enumerate(Allergen)}


def _allergen_rank(allergen: Allergen) -> tuple[int, str]:
    return _ALLERGEN_RANK.get(allergen, len(_ALLERGEN_RANK)), str(allergen)


def _name(problem: Problem, recipe_id: int) -> str:
    recipe = problem.recipes.get(recipe_id)
    return recipe.name if recipe else f"recipe {recipe_id}"


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def _unique(ids: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(ids))


def _money(minor: int) -> str:
    return f"{minor // 100:,}.{minor % 100:02d}"
