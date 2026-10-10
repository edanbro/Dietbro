import ast
import importlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import date
from itertools import product
from pathlib import Path
from random import Random
from typing import cast

import pytest

from larder_solver.diagnose import diagnose
from larder_solver.metrics import day_totals
from larder_solver.problem import (
    Allergen,
    AnimalTag,
    Band,
    Diet,
    Food,
    Ingredient,
    Lot,
    Macros,
    Meal,
    Nutrient,
    Plan,
    Problem,
    Profile,
    Recipe,
    Slot,
    SlotSpec,
    Targets,
)
from larder_solver.scenarios import infeasible, planted, synthetic_catalog
from larder_solver.validate import hard, validate

B, L, D, S = Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER, Slot.SNACK
MAINS = frozenset({L, D})
START = date(2026, 1, 5)  # a Monday
CATALOG = synthetic_catalog(0)

FOODS = {
    f.id: f
    for f in (
        Food(1, "oats", price_per_kg=200),
        Food(2, "peanuts", allergens=frozenset({Allergen.PEANUTS}), price_per_kg=800),
        Food(3, "beef", animal=frozenset({AnimalTag.MEAT}), price_per_kg=900),
        Food(4, "rice", price_per_kg=300),
        Food(5, "saffron", price_per_kg=100_000),
    )
}
RESTRICTED = Profile(allergens=frozenset({Allergen.PEANUTS}), diet=Diet.VEGETARIAN)
KCAL = Band(1200, 3000)


def rec(rid: int, slots: frozenset[Slot], kcal: int, *ingredients: tuple[int, int]) -> Recipe:
    return Recipe(
        rid,
        f"Recipe {rid}",
        slots,
        Macros(kcal, 20, 10, 40),
        tuple(Ingredient(f, g) for f, g in ingredients or ((4, 100),)),
    )


def breakfasts(n: int, kcal: int = 300, start: int = 1) -> list[Recipe]:
    return [rec(start + i, frozenset({B}), kcal, (1, 80)) for i in range(n)]


def mains(n: int, kcal: int = 400, start: int = 101) -> list[Recipe]:
    return [rec(start + i, MAINS, kcal, (4, 100)) for i in range(n)]


def world(
    recipes: Sequence[Recipe] | None = None,
    *,
    days: int = 7,
    kcal: Band = KCAL,
    floor: int = 1200,
    weekly: Band | None = None,
    profile: Profile = RESTRICTED,
    budget: int | None = None,
    locked: Mapping[tuple[int, Slot], Meal | None] | None = None,
    extra: Mapping[int, Macros] | None = None,
    pantry: Sequence[Lot] = (),
    repeats: Mapping[Slot, int] | None = None,
) -> Problem:
    """Breakfast (1-3 portions), lunch (1-4), dinner (2-4), each recipe a candidate of every
    slot it fits; by default 4 breakfasts (300 kcal) and 8 mains (400 kcal), all safe."""
    recipes = list(recipes) if recipes is not None else breakfasts(4) + mains(8)
    caps = {B: 4} if repeats is None else repeats
    limits = {B: (1, 3), L: (1, 4), D: (2, 4)}
    slots = tuple(
        SlotSpec(
            slot,
            True,
            tuple(r.id for r in recipes if slot in r.meal_types),
            lo,
            hi,
            caps.get(slot),
        )
        for slot, (lo, hi) in limits.items()
    )
    return Problem(
        start=START,
        days=days,
        slots=slots,
        recipes={r.id: r for r in recipes},
        foods=FOODS,
        targets=Targets(
            daily={Nutrient.KCAL: kcal},
            weekly={} if weekly is None else {Nutrient.KCAL: weekly},
            calorie_floor=floor,
        ),
        profile=profile,
        pantry=tuple(pantry),
        budget=budget,
        locked=locked or {},
        extra=extra or {},
    )


def test_a_feasible_world_has_no_diagnosis() -> None:
    assert diagnose(world()) == []


# --- scenarios -----------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(60))
def test_planted_scenarios_have_no_diagnosis(seed: int) -> None:
    # Every check is a necessary condition and the witness meets them all.
    assert diagnose(planted(seed).problem) == []


@pytest.mark.parametrize(("days", "k"), [(1, 10), (3, 5), (14, 40)])
def test_planted_scenarios_of_other_sizes_have_no_diagnosis(days: int, k: int) -> None:
    for seed in range(5):
        assert diagnose(planted(seed, CATALOG, days=days, k=k).problem) == []
        small = synthetic_catalog(seed, n_recipes=60, n_foods=40)
        assert diagnose(planted(seed, small, days=days, k=k).problem) == []


@pytest.mark.parametrize("seed", range(50))
def test_every_infeasible_scenario_is_caught(seed: int) -> None:
    messages = diagnose(infeasible(seed).problem)
    assert messages
    assert all("kcal minimum" in m for m in messages)


# --- candidates and repeat capacity --------------------------------------------------------------


def test_no_allowed_breakfast() -> None:
    peanut = [rec(i, frozenset({B}), 300, (2, 30)) for i in (1, 2)]
    beef = rec(3, frozenset({B}), 300, (3, 50))
    assert diagnose(world([*peanut, beef, *mains(8)])) == [
        "No breakfast fits your allergies and diet"
    ]


def test_no_breakfast_without_restrictions() -> None:
    assert diagnose(world(mains(8), profile=Profile())) == ["No breakfast recipe is available"]


def test_only_allowed_eligible_candidates_count() -> None:
    p = world()
    # A main listed as a breakfast candidate doesn't fit the slot; a peanut porridge isn't
    # allowed; a recipe that isn't a candidate isn't used at all.
    porridge = rec(9, frozenset({B}), 300, (2, 30))
    spare = rec(10, frozenset({B}), 300)
    recipes = {**p.recipes, 9: porridge, 10: spare}
    slots = (replace(p.slots[0], candidates=(101, 9)), *p.slots[1:])
    assert diagnose(replace(p, recipes=recipes, slots=slots)) == [
        "No breakfast fits your allergies and diet"
    ]


def test_repeat_capacity_of_one_slot() -> None:
    p = world(breakfasts(3) + mains(8), repeats={B: 2})
    assert diagnose(p) == [
        "Only 3 breakfasts fit your allergies and diet; a week needs at least 4 (each at most "
        "twice)"
    ]
    assert diagnose(world(breakfasts(4) + mains(8), repeats={B: 2})) == []  # 8 >= 7


def test_lunch_and_dinner_share_repeat_capacity() -> None:
    # Lunch alone (8 >= 7) and dinner alone are fine; together they need 14 meals.
    assert diagnose(world(breakfasts(4) + mains(4))) == [
        "Only 4 lunches and dinners fit your allergies and diet; a week needs at least 7 "
        "(each at most twice)"
    ]
    starters = [rec(201 + i, frozenset({L}), 400) for i in range(3)]
    assert diagnose(world(breakfasts(4) + mains(4) + starters)) == []


def test_capacity_wording_without_restrictions_and_for_shorter_plans() -> None:
    p = world(breakfasts(1) + mains(8), days=3, profile=Profile(), repeats={B: 2})
    assert diagnose(p) == [
        "Only 1 breakfast is available; 3 days need at least 2 (each at most twice)"
    ]
    p = world(breakfasts(2) + mains(8), days=5, profile=Profile(), repeats={B: 2})
    assert diagnose(p) == [
        "Only 2 breakfasts are available; 5 days need at least 3 (each at most twice)"
    ]


def test_capacity_wording_for_one_shared_recipe() -> None:
    # Lunch alone and dinner alone can each use the one main 7 times, but not both.
    p = world(breakfasts(4) + mains(1), repeats={B: 4, L: 7, D: 7})
    assert diagnose(p) == [
        "Only 1 lunch or dinner fits your allergies and diet; a week needs at least 2 (each at "
        "most 7 times)"
    ]


def test_capacity_wording_when_caps_differ() -> None:
    # A breakfast that is also a lunch takes lunch's tighter cap (2): 4 + 2 < 7 breakfasts.
    brunch = rec(9, frozenset({B, L}), 300, (1, 80))
    assert diagnose(world([*breakfasts(1), brunch, *mains(8)])) == [
        "Only 2 breakfasts fit your allergies and diet, enough for 6 of the 7 breakfasts to "
        "plan (each at most 2 to 4 times)"
    ]


def test_locked_meals_use_up_repeats() -> None:
    # Four snack locks use breakfasts 1 and 2 twice each (locks skip eligibility, not caps):
    # the 4 breakfasts can now fill only 4 of the 7 open breakfasts.
    p = world(breakfasts(4) + mains(8), repeats={B: 2})
    snack = SlotSpec(S, False, (), 1, 2, None)
    locked: dict[tuple[int, Slot], Meal | None] = {
        (d, S): Meal(d, S, 1 + d // 2, 1) for d in range(4)
    }
    p = replace(p, slots=(*p.slots, snack), locked=locked)
    assert diagnose(p) == [
        "Only 4 breakfasts fit your allergies and diet, enough for 4 of the 7 breakfasts left to "
        "plan (each at most twice)"
    ]


def test_slots_locked_empty_need_no_recipe() -> None:
    p = world(breakfasts(3) + mains(8), repeats={B: 2})
    assert diagnose(p) != []
    # Monday's breakfast stays empty (eaten out, say): 6 open breakfasts, room for 6.
    assert diagnose(replace(p, locked={(0, B): None}, extra={0: Macros(300)})) == []


# --- kcal ----------------------------------------------------------------------------------------


def test_kcal_out_of_reach_every_day() -> None:
    small = breakfasts(4, kcal=100) + mains(8, kcal=100)  # at most 300 + 400 + 400 kcal
    assert diagnose(world(small)) == [
        "Every day: even the largest meals that fit reach only 1,100 kcal, below your 1,200 kcal "
        "floor"
    ]
    assert diagnose(world(small, floor=800, kcal=Band(1500, 2000))) == [
        "Every day: even the largest meals that fit reach only 1,100 kcal, below your 1,500 kcal "
        "minimum"
    ]


def test_extra_counts_toward_the_day() -> None:
    # Smallest day: 300 + 400 + 800 = 1,500 kcal, plus 2,000 eaten off-plan on Tuesday.
    p = world(extra={1: Macros(2000)})
    assert diagnose(p) == [
        "Tue: even the smallest meals that fit come to 3,500 kcal (with 2,000 kcal eaten "
        "off-plan), above your 3,000 kcal maximum"
    ]


def test_locks_count_toward_the_day() -> None:
    big = Meal(2, D, 101, 10)  # 4,000 kcal, more portions than dinner allows: locks may
    locked: dict[tuple[int, Slot], Meal | None] = {
        (2, D): big,
        (3, L): None,  # Thursday: only breakfast (at most 900) and dinner (at most 1,600) left
        (3, D): None,
    }
    assert diagnose(world(locked=locked)) == [
        "Wed: even the smallest meals that fit come to 4,700 kcal (with your fixed meals), above "
        "your 3,000 kcal maximum",
        "Thu: even the largest meals that fit reach only 900 kcal, below your 1,200 kcal floor",
    ]


def test_extra_and_locks_can_make_a_day_feasible() -> None:
    small = breakfasts(4, kcal=100) + mains(8, kcal=100)  # at most 1,100 kcal a day
    assert diagnose(world(small, days=2)) != []
    # Mon: 200 off-plan + 1,100; Tue: a locked 600 kcal lunch + 300 + 400.
    p = world(small, days=2, extra={0: Macros(200)}, locked={(1, L): Meal(1, L, 101, 6)})
    assert diagnose(p) == []
    p = world(small, days=2, kcal=Band(1400, 2000), extra={0: Macros(200)})
    assert diagnose(p) == [
        "Mon: even the largest meals that fit reach only 1,300 kcal (with 200 kcal eaten "
        "off-plan), below your 1,400 kcal minimum",
        "Tue: even the largest meals that fit reach only 1,100 kcal, below your 1,400 kcal minimum",
    ]


def test_days_failing_alike_are_grouped() -> None:
    locked: dict[tuple[int, Slot], Meal | None] = {(d, L): None for d in (0, 2)}
    locked |= {(d, D): None for d in (0, 2)}
    assert diagnose(world(locked=locked)) == [
        "Mon and Wed: even the largest meals that fit reach only 900 kcal, below your 1,200 "
        "kcal floor"
    ]


def test_floor_above_the_daily_maximum() -> None:
    assert diagnose(world(kcal=Band(900, 1100))) == [
        "Your daily maximum of 1,100 kcal is below your 1,200 kcal floor"
    ]


def test_weekly_kcal_band() -> None:
    # Days reach 1,500..3,000 (clipped to the daily band): 10,500..21,000 a week.
    assert diagnose(world(weekly=Band(21_001, None))) == [
        "This week: even the largest meals that fit reach only 21,000 kcal, below your 21,001 "
        "kcal weekly minimum"
    ]
    assert diagnose(world(weekly=Band(None, 10_499))) == [
        "This week: even the smallest meals that fit come to 10,500 kcal, above your 10,499 "
        "kcal weekly maximum"
    ]
    assert diagnose(world(weekly=Band(10_500, 21_000))) == []
    # Off-plan intake counts toward the week too.
    assert diagnose(world(weekly=Band(None, 10_499), extra={0: Macros(-1)})) == []


# --- budget --------------------------------------------------------------------------------------


def test_budget_lower_bound() -> None:
    # Cheapest kcal: rice mains, 100 g x 300 per kg = 30,000 millipence per 400 kcal portion.
    # Each day needs 1,200 kcal, and at least 1 breakfast (16,000) + 1 lunch (30,000) + 2
    # dinner portions (60,000) = 106,000 millipence: 7 x 106,000 = 742,000 = 742 pence.
    assert diagnose(world(budget=742)) == []
    assert diagnose(world(budget=741)) == [
        "Even the cheapest meals that fit would cost at least 7.42, over your 7.41 budget"
    ]


def test_budget_counts_kcal_still_needed() -> None:
    # A 3,000 kcal floor: the cheapest meals give 300 + 400 + 800 kcal for 106,000 millipence.
    # The other 1,500 kcal come cheapest from breakfast (16,000 per 300 kcal) up to its 900
    # kcal maximum, 600 kcal for 32,000, then 900 kcal of rice mains (30,000 per 400 kcal) for
    # 67,500: 205,500 a day, 1,438,500 a week = 1,439 pence. Breakfast's 900 kcal cap matters:
    # without it the bound would be 3,000 kcal of breakfast kcal, 1,120 pence a week.
    p = world(kcal=Band(3000, 3500), floor=3000, budget=1438)
    assert diagnose(p) == [
        "Even the cheapest meals that fit would cost at least 14.39, over your 14.38 budget"
    ]
    assert diagnose(replace(p, budget=1439)) == []


def test_budget_counts_the_weekly_kcal_minimum() -> None:
    # Days need only 1,200 kcal (742 pence a week, see above), but the week needs 14,000: at
    # least 14,000 kcal at the cheapest kcal (breakfast, 160 per 3 kcal) = 746,667 millipence.
    p = world(weekly=Band(14_000, None), budget=746)
    assert diagnose(p) == [
        "Even the cheapest meals that fit would cost at least 7.47, over your 7.46 budget"
    ]
    assert diagnose(replace(p, budget=747)) == []


def test_budget_counts_the_pantry_and_locked_meals() -> None:
    p = world(budget=741)
    assert diagnose(replace(p, pantry=(Lot(4, 1000, None),))) == []  # 300 pence of rice
    expired = diagnose(replace(p, pantry=(Lot(4, 1, None),)))
    assert expired == [
        "Even the cheapest meals that fit would cost at least 7.42 after using your pantry, "
        "over your 7.41 budget"
    ]
    assert diagnose(replace(p, pantry=(Lot(4, 1000, -1),))) != []  # expired lots don't count
    saffron = rec(9, frozenset({B}), 300, (5, 10))  # 1,000,000 millipence a portion
    p = world([*breakfasts(4), *mains(8), saffron], budget=1700)
    assert diagnose(p) == []
    # Locked on Monday: 1,000,000 + Monday's lunch and dinner (90,000) + 6 x 106,000.
    p = replace(p, locked={(0, B): Meal(0, B, 9, 1)})
    assert diagnose(p) == [
        "Even the cheapest meals that fit would cost at least 17.26, over your 17.00 budget"
    ]


# --- locks ---------------------------------------------------------------------------------------


def test_unsafe_locks() -> None:
    curry = Recipe(9, "Peanut curry", MAINS, Macros(400, 20, 10, 40), (Ingredient(2, 30),))
    mystery = Recipe(10, "Mystery stew", MAINS, Macros(400, 20, 10, 40), (Ingredient(99, 30),))
    p = world([*breakfasts(4), *mains(8), curry, mystery])
    locked: dict[tuple[int, Slot], Meal | None] = {
        (2, D): Meal(2, D, 9, 2),
        (0, L): Meal(0, L, 10, 2),
    }
    assert diagnose(replace(p, locked=locked)) == [
        "Your fixed Mon lunch, Mystery stew, uses an ingredient we have no data for",
        "Your fixed Wed dinner, Peanut curry, doesn't fit your allergies and diet",
    ]


# --- soundness -----------------------------------------------------------------------------------


def tiny(seed: int) -> Problem:
    """A random two-day problem small enough to enumerate every plan."""
    rng = Random(seed)
    foods = {
        1: Food(1, "oats", price_per_kg=rng.randint(100, 2000)),
        2: Food(2, "peanuts", allergens=frozenset({Allergen.PEANUTS}), price_per_kg=800),
        3: Food(3, "beef", animal=frozenset({AnimalTag.MEAT}), price_per_kg=rng.randint(500, 2000)),
        4: Food(4, "rice", price_per_kg=rng.randint(100, 2000)),
    }

    def make(rid: int, slots: frozenset[Slot], lo: int, hi: int) -> Recipe:
        picked = [rng.choice([1, 4])]
        if rng.random() < 0.4:
            picked.append(rng.choice([f for f in (1, 2, 3, 4) if f != picked[0]]))
        return Recipe(
            rid,
            f"Recipe {rid}",
            slots,
            Macros(rng.randint(lo, hi), rng.randint(5, 40), 10, 40),
            tuple(Ingredient(f, rng.randint(10, 150)) for f in picked),
        )

    recipes = [make(1, frozenset({B}), 150, 500), make(2, frozenset({B}), 150, 500)]
    recipes += [make(3, MAINS, 250, 800), make(4, MAINS, 250, 800)]
    profile = rng.choice(
        [
            Profile(),
            Profile(),
            Profile(allergens=frozenset({Allergen.PEANUTS})),
            Profile(diet=Diet.VEGETARIAN),
            RESTRICTED,
        ]
    )
    low = rng.randint(700, 1900)
    weekly = {Nutrient.KCAL: Band(None, rng.randint(1500, 3500))} if rng.random() < 0.3 else {}
    locked: dict[tuple[int, Slot], Meal | None] = {}
    if rng.random() < 0.4:
        day, slot = rng.randrange(2), rng.choice([B, L, D])
        rid = rng.choice([1, 2] if slot is B else [3, 4])
        locked[(day, slot)] = rng.choice([None, Meal(day, slot, rid, rng.randint(1, 2))])
    return Problem(
        start=START,
        days=2,
        slots=(
            SlotSpec(B, True, (1, 2), 1, 2, rng.choice([1, 2])),
            SlotSpec(L, True, (3, 4), 1, 1),
            SlotSpec(D, True, (3, 4), 1, 2),
        ),
        recipes={r.id: r for r in recipes},
        foods=foods,
        targets=Targets(
            daily={Nutrient.KCAL: Band(low, low + rng.randint(100, 1200))},
            weekly=weekly,
            calorie_floor=rng.choice([500, 800, 1000, 1200]),
        ),
        profile=profile,
        pantry=(Lot(rng.randint(1, 4), rng.randint(0, 400), rng.choice([None, -1, 0, 1])),),
        budget=rng.choice([None, rng.randint(50, 700)]),
        locked=locked,
        extra={rng.randrange(2): Macros(rng.randint(0, 900))} if rng.random() < 0.4 else {},
        max_repeats=rng.choice([1, 2, 2, 2, 3]),
    )


def every_plan(problem: Problem) -> Iterator[Plan]:
    """Every plan made of candidates within the portion ranges that honours the locks."""
    cells: list[list[Meal | None]] = []
    for day in range(problem.days):
        for spec in problem.slots:
            if (day, spec.slot) in problem.locked:
                cells.append([problem.locked[(day, spec.slot)]])
                continue
            lo, hi = problem.portion_range(spec.slot)
            meals: list[Meal | None] = [
                Meal(day, spec.slot, r, n) for r in spec.candidates for n in range(lo, hi + 1)
            ]
            cells.append(meals if spec.required else [*meals, None])
    for chosen in product(*cells):
        yield Plan(tuple(m for m in chosen if m is not None))


def is_valid(problem: Problem, plan: Plan) -> bool:
    """`hard(validate(...)) == []`, skipping the validator for days outside the kcal band."""
    band = problem.targets.daily.get(Nutrient.KCAL, Band())
    floor = problem.targets.calorie_floor
    if any(not band.contains(t.kcal) or t.kcal < floor for t in day_totals(problem, plan)):
        return False
    return not hard(validate(problem, plan))


def test_diagnosis_is_sound_on_enumerable_problems() -> None:
    """Whenever diagnose names a reason, no plan at all meets the hard rules."""
    diagnosed = feasible = 0
    kinds: set[str] = set()
    for seed in range(120):
        p = tiny(seed)
        messages = diagnose(p)
        valid = next((plan for plan in every_plan(p) if is_valid(p, plan)), None)
        assert not (messages and valid), (seed, messages, valid)
        diagnosed += bool(messages)
        feasible += valid is not None
        kinds |= {k for k in ("Only", "kcal", "budget", "fixed") if any(k in m for m in messages)}
    # Neither vacuous nor always on, and every kind of check fires somewhere.
    assert diagnosed >= 40
    assert feasible >= 20
    assert kinds == {"Only", "kcal", "budget", "fixed"}


# --- independence --------------------------------------------------------------------------------


def imports(module: str) -> set[str]:
    source = cast(str, importlib.import_module(module).__file__)
    imported: set[str] = set()
    for node in ast.walk(ast.parse(Path(source).read_text())):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    return {name for name in imported if name.split(".")[0] == "larder_solver"}


def test_diagnose_uses_the_prefilter_not_the_validator_or_a_planner() -> None:
    assert imports("larder_solver.diagnose") <= {
        "larder_solver.candidates",
        "larder_solver.metrics",
        "larder_solver.problem",
    }
