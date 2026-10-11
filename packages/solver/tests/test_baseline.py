import ast
import importlib
import os
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import cast

import pytest

from larder_solver.baseline import greedy
from larder_solver.metrics import changed_slots, day_totals, repeat_counts, score
from larder_solver.problem import (
    Allergen,
    Band,
    Food,
    Ingredient,
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
)
from larder_solver.scenarios import infeasible, planted, realistic, replan, synthetic_catalog
from larder_solver.validate import (
    SAFETY_CODES,
    STRUCTURAL_CODES,
    Code,
    Violation,
    hard,
    validate,
)

B, L, D, S = Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER, Slot.SNACK
START = date(2026, 1, 5)  # a Monday
CATALOG = synthetic_catalog(0)
NEVER = SAFETY_CODES | STRUCTURAL_CODES | {Code.REPEATS}  # greedy guarantees these by design


def broken(problem: Problem, plan: Plan) -> list[Violation]:
    return [v for v in validate(problem, plan) if v.code in NEVER]


def planned(result: PlanResult) -> Plan:
    assert result.status is Status.FEASIBLE, result.notes
    assert result.plan is not None
    return result.plan


# --- planted scenarios ---------------------------------------------------------------------------

SEEDS = range(60)


@pytest.mark.parametrize("seed", SEEDS)
def test_planted_plans_are_safe_and_well_formed(seed: int) -> None:
    scenario = planted(seed)
    p = scenario.problem
    result = greedy(p)
    plan = planned(result)
    assert result.planner == "greedy"
    assert broken(p, plan) == []  # no safety, structural or repeat violations
    assert not any(m.recipe_id in scenario.decoys for m in plan.meals)
    for day in range(p.days):  # every required slot filled, nothing doubled
        for spec in p.slots:
            meals = [m for m in plan.meals if (m.day, m.slot) == (day, spec.slot)]
            assert len(meals) == (1 if spec.required else len(meals[:1]))
    assert all(t.kcal >= p.targets.calorie_floor for t in day_totals(p, plan))
    assert result.objective == score(p, plan).total
    assert result.bound is None


def test_planted_hard_validity_rate() -> None:
    """How often the baseline meets every hard rule (kcal bands and budget included) on
    planted scenarios. Measured when written: 100% of seeds 0-99. The kcal bands and the
    budget are not guaranteed, so this only guards against regressions."""
    valid = sum(
        not hard(validate(s.problem, planned(greedy(s.problem)))) for s in map(planted, SEEDS)
    )
    assert valid >= 0.95 * len(SEEDS)


@pytest.mark.parametrize("seed", range(10))
def test_planted_plans_of_other_sizes(seed: int) -> None:
    for days, k in ((1, 10), (3, 5), (14, 40)):
        scenario = planted(seed, CATALOG, days=days, k=k)
        plan = planned(greedy(scenario.problem))
        assert broken(scenario.problem, plan) == []
        assert not any(m.recipe_id in scenario.decoys for m in plan.meals)


@pytest.mark.parametrize("seed", range(20))
def test_realistic_plans_are_safe_and_well_formed(seed: int) -> None:
    p = realistic(seed, CATALOG).problem
    result = greedy(p)
    if result.plan is None:  # no feasibility guarantee here, but never a half-made plan
        assert result.status is Status.INFEASIBLE
        assert result.notes
        return
    assert broken(p, result.plan) == []


@pytest.mark.parametrize("seed", range(20))
def test_infeasible_band_gives_the_closest_plan_above_the_floor(seed: int) -> None:
    # The band is out of reach but the floor isn't: a plan that misses only the kcal band.
    p = infeasible(seed).problem
    result = greedy(p)
    plan = planned(result)
    codes = {v.code for v in hard(validate(p, plan))}
    assert codes <= {Code.DAILY_BAND, Code.WEEKLY_BAND, Code.BUDGET}
    assert Code.DAILY_BAND in codes
    assert any("kcal band was out of reach" in n for n in result.notes)


def test_deterministic() -> None:
    p = planted(7).problem
    assert greedy(p).plan == greedy(p).plan


_DIGEST = """
from larder_solver.baseline import greedy
from larder_solver.scenarios import planted
print([greedy(planted(seed).problem).plan for seed in (3, 11)])
"""


def test_deterministic_across_hash_seeds() -> None:
    plans = {
        subprocess.run(
            [sys.executable, "-c", _DIGEST],
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for hash_seed in ("1", "2")
    }
    assert len(plans) == 1


def test_fast_at_full_size() -> None:
    """k=40 candidates, 4 slots, 7 days: typically 20-40 ms; the bound is generous for shared
    CI machines."""
    for seed in range(5):
        result = greedy(realistic(seed, CATALOG).problem)
        assert result.wall_ms <= 1_000


# --- locks, extra, replans -----------------------------------------------------------------------


def test_locks_are_honoured() -> None:
    scenario = planted(5)
    p = scenario.problem
    witness = scenario.witness
    assert witness is not None
    fixed = witness.meals[1]  # a witness meal: allowed, eligible
    big = replace(witness.meals[4], portions=9)  # outside the portion range: locks may
    locked: dict[tuple[int, Slot], Meal | None] = {
        (fixed.day, fixed.slot): fixed,
        (big.day, big.slot): big,
        (3, L): None,
    }
    p = replace(p, locked=locked, extra={3: Macros(900, 30, 30, 100)})
    plan = planned(greedy(p))
    assert fixed in plan.meals
    assert big in plan.meals
    assert plan.at(3, L) is None
    assert broken(p, plan) == []


def test_extra_counts_toward_the_day() -> None:
    # Lunch eaten out (locked empty, 900 kcal off-plan): the day still lands in the band.
    p = small_world(days=3, kcal=Band(1500, 1800))
    p = replace(p, locked={(1, L): None}, extra={1: Macros(900, 20, 30, 120)})
    plan = planned(greedy(p))
    assert plan.at(1, L) is None
    assert 1500 <= day_totals(p, plan)[1].kcal <= 1800
    assert hard(validate(p, plan)) == []


def test_an_unsafe_lock_means_no_plan() -> None:
    p = small_world()
    peanut = Recipe(99, "Satay", frozenset({D}), Macros(500, 20, 20, 50), (Ingredient(2, 30),))
    p = replace(p, recipes={**p.recipes, 99: peanut}, locked={(1, D): Meal(1, D, 99, 2)})
    result = greedy(p)
    assert (result.status, result.plan) == (Status.INFEASIBLE, None)
    assert result.notes == ("Tue dinner: the fixed meal isn't allowed",)


def test_replanning_keeps_the_previous_plan() -> None:
    for seed in range(10):
        p = planted(seed).problem
        first = planned(greedy(p))
        assert changed_slots(first, planned(greedy(p, first))) == 0
        # Without its most used recipe, a replan changes little more than that recipe's slots.
        gone, uses = Counter(m.recipe_id for m in first.meals).most_common(1)[0]
        slots = tuple(
            replace(s, candidates=tuple(r for r in s.candidates if r != gone)) for s in p.slots
        )
        p = replace(p, slots=slots)
        again = planned(greedy(p, first))
        assert changed_slots(first, again) <= uses + 3
        assert changed_slots(first, again) < changed_slots(first, planned(greedy(p)))


# --- floor, band and caps ------------------------------------------------------------------------

FOODS = {
    1: Food(1, "oats", price_per_kg=200),
    2: Food(2, "peanuts", allergens=frozenset({Allergen.PEANUTS}), price_per_kg=800),
    3: Food(3, "rice", price_per_kg=300),
}


def rec(rid: int, slots: frozenset[Slot], kcal: int, preference: int = 0) -> Recipe:
    return Recipe(
        rid,
        f"Recipe {rid}",
        slots,
        Macros(kcal, kcal // 20, kcal // 30, kcal // 8),
        (Ingredient(1 if B in slots else 3, 80),),
        preference=preference,
    )


def small_world(
    *, days: int = 7, kcal: Band | None = None, floor: int = 1200, main_kcal: int = 350
) -> Problem:
    """Breakfast (1-3 portions, cap 4), lunch (1-4), dinner (2-4), 4 breakfasts of 200 kcal
    and 8 mains a portion, peanut-allergic."""
    recipes = [rec(1 + i, frozenset({B}), 200) for i in range(4)]
    recipes += [rec(101 + i, frozenset({L, D}), main_kcal) for i in range(8)]

    def spec(slot: Slot, lo: int, hi: int, cap: int | None = None) -> SlotSpec:
        ids = tuple(r.id for r in recipes if slot in r.meal_types)
        return SlotSpec(slot, True, ids, lo, hi, cap)

    return Problem(
        start=START,
        days=days,
        slots=(spec(B, 1, 3, 4), spec(L, 1, 4), spec(D, 2, 4)),
        recipes={r.id: r for r in recipes},
        foods=FOODS,
        targets=Targets({Nutrient.KCAL: kcal or Band(1500, 2500)}, calorie_floor=floor),
        profile=Profile(allergens=frozenset({Allergen.PEANUTS})),
    )


def test_unreachable_floor_means_no_plan() -> None:
    # At most 3 x 200 + 4 x 100 + 4 x 100 = 1,400 kcal a day.
    result = greedy(small_world(main_kcal=100, kcal=Band(1500, 2000), floor=1500))
    assert (result.status, result.plan) == (Status.INFEASIBLE, None)
    assert result.notes == ("Mon: no meals that fit reach the 1,500 kcal floor",)


def test_the_band_is_met_whenever_a_day_can_reach_it() -> None:
    # Any day's combination can be repeated all week within the caps (16 breakfasts and 16
    # mains of room), so the band is reachable iff one day can land in it.
    days = {
        b * 200 + (lunch + dinner) * 350
        for b in range(1, 4)
        for lunch in range(1, 5)
        for dinner in range(2, 5)
    }
    reachable = 0
    for low in range(1200, 3000, 50):
        p = small_world(kcal=Band(low, low + 100))
        result = greedy(p)
        plan = planned(result)
        codes = {v.code for v in hard(validate(p, plan))}
        if any(low <= kcal <= low + 100 for kcal in days):
            reachable += 1
            assert codes == set(), low
        else:  # the closest day above the floor
            assert codes == {Code.DAILY_BAND}, low
            assert all(t.kcal >= 1200 for t in day_totals(p, plan))
    assert reachable >= 10


def test_repeat_caps_spread_a_favourite() -> None:
    p = small_world()
    favourite = replace(p.recipes[1], preference=100)
    plan = planned(greedy(replace(p, recipes={**p.recipes, 1: favourite})))
    assert repeat_counts(plan)[1] == 4  # breakfast's cap
    assert broken(p, plan) == []


def test_snacks_never_take_recipes_breakfast_still_needs() -> None:
    """The snack's favourite is also the breakfast fallback: taking it every day as a snack
    would leave too few breakfasts by Friday. The baseline keeps Hall's condition after each
    day, so the plan stays within the caps."""
    eggs = rec(1, frozenset({B}), 600, preference=100)  # cap 4 (breakfast)
    pot = rec(2, frozenset({B, S}), 600, preference=50)  # cap 4 (breakfast and snack)
    fruit = rec(3, frozenset({S}), 600)  # cap 7 (snack)
    p = Problem(
        start=START,
        days=7,
        slots=(SlotSpec(B, True, (1, 2), 1, 1, 4), SlotSpec(S, False, (2, 3), 1, 1, 7)),
        recipes={r.id: r for r in (eggs, pot, fruit)},
        foods=FOODS,
        targets=Targets({Nutrient.KCAL: Band(1200, 1300)}),  # a snack every day
    )
    plan = planned(greedy(p))
    assert hard(validate(p, plan)) == []
    # Mon: eggs and the pot as a snack. From Tue the pot is kept for the breakfasts after
    # eggs run out (Fri-Sun), so the snacks are fruit. Without the check: eggs + pot snack
    # Mon-Thu, and no breakfast left on Fri.
    assert repeat_counts(plan) == Counter({1: 4, 2: 4, 3: 6})


def test_a_snack_only_when_it_earns_its_place() -> None:
    p = small_world(kcal=Band(1200, 1400))
    snacks = [rec(201 + i, frozenset({S}), 150) for i in range(3)]
    p = replace(
        p,
        slots=(*p.slots, SlotSpec(S, False, tuple(r.id for r in snacks), 1, 2, 4)),
        recipes={**p.recipes, **{r.id: r for r in snacks}},
    )
    plan = planned(greedy(p))
    assert not any(m.slot is S for m in plan.meals)


# --- choices and day bands (replans) -------------------------------------------------------------


def test_chosen_cells_hold_one_of_their_recipes() -> None:
    p = small_world()
    choices = {(0, B): (3,), (2, D): (105,), (4, L): (101, 102)}
    plan = planned(greedy(replace(p, choices=choices)))
    for (day, slot), ids in choices.items():
        meal = plan.at(day, slot)
        assert meal is not None
        assert meal.recipe_id in ids
        lo, hi = p.portion_range(slot)
        assert lo <= meal.portions <= hi
    assert broken(replace(p, choices=choices), plan) == []


def test_a_chosen_recipe_need_not_be_a_candidate() -> None:
    p = small_world()
    special = rec(150, frozenset({L, D}), 350)
    p = replace(p, recipes={**p.recipes, 150: special}, choices={(3, D): (150,)})
    plan = planned(greedy(p))
    assert plan.at(3, D) == Meal(3, D, 150, cast(Meal, plan.at(3, D)).portions)
    assert sum(m.recipe_id == 150 for m in plan.meals) == 1
    assert broken(p, plan) == []


def test_a_choice_fills_an_optional_slot() -> None:
    p = small_world(kcal=Band(1200, 1400))
    snacks = [rec(201 + i, frozenset({S}), 150) for i in range(3)]
    p = replace(
        p,
        slots=(*p.slots, SlotSpec(S, False, tuple(r.id for r in snacks), 1, 2, 4)),
        recipes={**p.recipes, **{r.id: r for r in snacks}},
        choices={(1, S): (202,)},
    )
    plan = planned(greedy(p))
    assert [(m.day, m.recipe_id) for m in plan.meals if m.slot is S] == [(1, 202)]
    assert hard(validate(p, plan)) == []


def test_choices_still_get_the_hard_filters() -> None:
    p = small_world()
    satay = Recipe(99, "Satay", frozenset({L, D}), Macros(350, 20, 20, 50), (Ingredient(2, 30),))
    p = replace(p, recipes={**p.recipes, 99: satay})
    plan = planned(greedy(replace(p, choices={(2, D): (99, 103)})))
    assert cast(Meal, plan.at(2, D)).recipe_id == 103
    for ids, why in (((99,), "is allowed"), ((1, 2), "is a dinner recipe")):
        result = greedy(replace(p, choices={(2, D): ids}))
        assert (result.status, result.plan) == (Status.INFEASIBLE, None)
        assert result.notes == (f"Wed dinner: none of the chosen recipes {why}",)


def test_repeat_caps_are_kept_for_later_choices() -> None:
    # Left alone, the favourite main is used up (cap 2) before Saturday, leaving nothing for
    # the Saturday and Sunday that chose it. The capacity check after each day keeps it back.
    p = small_world()
    favourite = replace(p.recipes[101], preference=100)
    p = replace(p, recipes={**p.recipes, 101: favourite})
    assert [m.day for m in planned(greedy(p)).meals if m.recipe_id == 101] == [0, 4]
    p = replace(p, choices={(5, D): (101,), (6, L): (101,)})
    plan = planned(greedy(p))
    assert [(m.day, m.slot) for m in plan.meals if m.recipe_id == 101] == [(5, D), (6, L)]
    assert broken(p, plan) == []


def test_two_cells_chosen_as_the_same_dish() -> None:
    # Leftovers: Wednesday's lunch and dinner are both the stew. The baseline's own "a recipe
    # at most once a day" gives way to choices while the repeat cap has room for both.
    p = replace(small_world(), choices={(2, L): (104,), (2, D): (104,)})
    plan = planned(greedy(p))
    assert [(m.day, m.slot) for m in plan.meals if m.recipe_id == 104] == [(2, L), (2, D)]
    assert broken(p, plan) == []
    # With the stew already locked on Monday, one use is left: lunch takes the other choice.
    locked: dict[tuple[int, Slot], Meal | None] = {(0, D): Meal(0, D, 104, 2)}
    p = replace(p, locked=locked, choices={(2, L): (104, 105), (2, D): (104,)})
    plan = planned(greedy(p))
    assert [cast(Meal, plan.at(2, s)).recipe_id for s in (L, D)] == [105, 104]
    assert broken(p, plan) == []


def test_choices_beyond_a_repeat_cap_mean_no_plan() -> None:
    p = replace(small_world(), choices={(d, D): (101,) for d in (1, 3, 5)})
    result = greedy(p)
    assert (result.status, result.plan) == (Status.INFEASIBLE, None)
    assert result.notes == ("too few allowed recipes to fill every meal within the repeat limits",)


def test_replanning_with_a_choice_changes_little_else() -> None:
    for seed in range(10):
        scenario = planted(seed)
        p = scenario.problem
        first = planned(greedy(p))
        before = cast(Meal, first.at(3, D)).recipe_id
        spec = cast(SlotSpec, p.spec(D))
        wanted = next(r for r in spec.candidates if r not in scenario.decoys and r != before)
        p = replace(p, choices={(3, D): (wanted,)})
        again = planned(greedy(p, first))
        assert cast(Meal, again.at(3, D)).recipe_id == wanted
        assert broken(p, again) == []
        # The chosen cell, the chosen recipe's old place and a little rebalancing; without
        # the previous plan, 4-12 cells change.
        assert changed_slots(first, again) <= 4, seed
        assert changed_slots(first, again) < changed_slots(first, planned(greedy(p))), seed


def test_a_day_band_above_the_daily_maximum() -> None:
    # Tuesday's lunch was a 1,800 kcal pizza: the smallest day is 2,700 kcal.
    p = small_world(days=3, kcal=Band(1500, 1800))
    p = replace(p, locked={(1, L): None}, extra={1: Macros(1800, 40, 60, 200)})
    result = greedy(p)
    assert {v.code for v in hard(validate(p, planned(result)))} == {Code.DAILY_BAND}
    assert result.notes == ("Tue: the kcal band was out of reach (2,700 kcal)",)
    p = replace(p, day_kcal={1: Band(1500, 2900)})
    result = greedy(p)
    plan = planned(result)
    assert hard(validate(p, plan)) == []
    assert result.notes == ()
    assert [1500 <= t.kcal <= 1800 for t in day_totals(p, plan)] == [True, False, True]


def test_a_day_band_below_the_floor() -> None:
    # Tuesday's lunch and dinner skipped: breakfast reaches 600 kcal at most.
    p = small_world(days=3)
    p = replace(p, locked={(1, L): None, (1, D): None})
    result = greedy(p)
    assert (result.status, result.notes) == (
        Status.INFEASIBLE,
        ("Tue: no meals that fit reach the 1,200 kcal floor",),
    )
    p = replace(p, day_kcal={1: Band(600, 2500)})
    plan = planned(greedy(p))
    assert hard(validate(p, plan)) == []
    totals = [t.kcal for t in day_totals(p, plan)]
    assert totals[1] == 600
    assert all(1500 <= kcal <= 2500 for i, kcal in enumerate(totals) if i != 1)
    result = greedy(replace(p, day_kcal={1: Band(700, 2500)}))
    assert result.notes == ("Tue: no meals that fit reach the 700 kcal minimum for the day",)
    plan = planned(greedy(replace(p, day_kcal={1: Band(None, 300)})))  # no floor that day
    assert day_totals(p, plan)[1].kcal == 200


def test_a_day_band_reachable_only_with_a_low_ranked_meal() -> None:
    # Tuesday: breakfast eaten, lunch off-plan, dinner skipped; only the snack is open. Five
    # liked 100 kcal snacks rank above a disliked 400 kcal one, and the day's band (clipped
    # to what the open cells reach, as a replan sets it) needs that one at two portions.
    p = small_world(days=3)
    snacks = [rec(201 + i, frozenset({S}), 100, preference=2) for i in range(5)]
    snacks.append(rec(206, frozenset({S}), 400, preference=-2))
    p = replace(
        p,
        slots=(*p.slots, SlotSpec(S, False, tuple(r.id for r in snacks), 1, 2)),
        recipes={**p.recipes, **{r.id: r for r in snacks}},
        locked={(1, B): None, (1, L): None, (1, D): None},
        extra={1: Macros(300, 10, 10, 40)},
        day_kcal={1: Band(300 + 800, 2500)},
    )
    plan = planned(greedy(p))
    assert hard(validate(p, plan)) == []
    assert plan.at(1, S) == Meal(1, S, 206, 2)
    assert day_totals(p, plan)[1].kcal == 1100


def day_minimum(problem: Problem, day: int) -> int:
    band = problem.day_kcal.get(day)
    if band is None:
        return problem.targets.calorie_floor
    return band.min if band.min is not None else 0


@pytest.mark.parametrize("seed", range(40))
def test_replan_scenarios_are_safe_and_well_formed(seed: int) -> None:
    scenario = replan(seed)
    p = scenario.problem
    plan = planned(greedy(p))
    assert broken(p, plan) == []  # choices honoured (CHOICE is structural), locks, filters
    assert not any(m.recipe_id in scenario.decoys for m in plan.meals)
    assert all(t.kcal >= day_minimum(p, d) for d, t in enumerate(day_totals(p, plan)))


def test_replan_hard_validity_rate() -> None:
    """How often the baseline meets every hard rule on replan scenarios. Measured when
    written: 99 of seeds 0-99 (one weekly kcal band miss)."""
    plans = ((s.problem, planned(greedy(s.problem))) for s in map(replan, SEEDS))
    valid = sum(not hard(validate(problem, plan)) for problem, plan in plans)
    assert valid >= 0.95 * len(SEEDS)


# --- independence --------------------------------------------------------------------------------


def test_baseline_never_consults_the_validator() -> None:
    source = cast(str, importlib.import_module("larder_solver.baseline").__file__)
    imported: set[str] = set()
    for node in ast.walk(ast.parse(Path(source).read_text())):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
    assert {m for m in imported if m.startswith("larder_solver")} <= {
        "larder_solver.candidates",
        "larder_solver.metrics",
        "larder_solver.problem",
    }
