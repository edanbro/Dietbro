import ast
import importlib
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from larder_solver.problem import (
    SLOT_ORDER,
    Allergen,
    AnimalTag,
    Band,
    Diet,
    Food,
    Ingredient,
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
from larder_solver.scenarios import planted
from larder_solver.validate import (
    HARD_FILTER_CODES,
    SAFETY_CODES,
    STRUCTURAL_CODES,
    Code,
    Violation,
    hard,
    validate,
)

B, L, D, S = Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER, Slot.SNACK
MAINS = frozenset({L, D})

FOODS = {
    f.id: f
    for f in (
        Food(1, "peanuts", "Legumes", allergens=frozenset({Allergen.PEANUTS}), price_per_kg=800),
        Food(2, "beef mince", "Beef", animal=frozenset({AnimalTag.MEAT}), price_per_kg=900),
        Food(3, "oats", "Cereal Grains and Pasta", price_per_kg=200),
        Food(4, "rice", "Cereal Grains and Pasta", price_per_kg=300),
        Food(5, "milk", "Dairy", frozenset({Allergen.MILK}), frozenset({AnimalTag.DAIRY}), 100),
        Food(6, "coriander", "Spices and Herbs", price_per_kg=2000),
        Food(7, "salt", "Spices and Herbs"),
    )
}


def recipe(
    rid: int,
    name: str,
    slots: frozenset[Slot],
    kcal: int,
    protein: int,
    *ingredients: tuple[int, int],
    unresolved: int = 0,
    text_allergens: frozenset[Allergen] = frozenset(),
) -> Recipe:
    return Recipe(
        rid,
        name,
        slots,
        Macros(kcal, protein, 10, 40),
        tuple(Ingredient(f, g) for f, g in ingredients),
        unresolved=unresolved,
        text_allergens=text_allergens,
    )


RECIPES = {
    r.id: r
    for r in (
        recipe(10, "Porridge", frozenset({B}), 200, 4, (3, 40), (5, 100), (7, 0)),
        recipe(11, "Bircher muesli", frozenset({B}), 220, 5, (3, 50), (5, 50)),
        recipe(20, "Vegetable risotto", MAINS, 350, 10, (4, 80), (5, 20)),
        recipe(21, "Bean chilli", MAINS, 330, 15, (4, 60)),
        recipe(22, "Lentil soup", frozenset({L}), 180, 9, (4, 20)),
        recipe(30, "Fruit pot", frozenset({S}), 100, 1),
        recipe(40, "Thai green curry", MAINS, 350, 10, (1, 20), (4, 80)),
        recipe(41, "Beef stew", MAINS, 350, 10, (2, 100)),
        recipe(42, "Coriander salad", MAINS, 350, 10, (6, 10), (4, 80)),
        recipe(43, "Mystery bake", MAINS, 350, 10, (4, 80), unresolved=1),
        recipe(44, "Secret stew", MAINS, 350, 10, (99, 10), (4, 80)),
        recipe(45, "Satay noodles", MAINS, 350, 10, text_allergens=frozenset({Allergen.PEANUTS})),
    )
}

BASE = Problem(
    start=date(2026, 1, 5),  # a Monday
    days=2,
    slots=(
        SlotSpec(B, True, (10, 11), min_portions=1, max_portions=3, max_repeats=4),
        SlotSpec(L, True, (20, 21, 22)),
        SlotSpec(D, True, (20, 21), min_portions=2),
        SlotSpec(S, False, (30,), max_portions=2, max_repeats=4),
    ),
    recipes=RECIPES,
    foods=FOODS,
    targets=Targets(
        daily={Nutrient.KCAL: Band(1200, 2000), Nutrient.PROTEIN: Band(30, None)},
        weekly={Nutrient.PROTEIN: Band(60, 200)},
        calorie_floor=1200,
    ),
    profile=Profile(
        allergens=frozenset({Allergen.PEANUTS}),
        avoid_food_ids=frozenset({6}),
        diet=Diet.VEGETARIAN,
    ),
)
# Mon 400 + 360 + 700 = 1,460 kcal, Tue 440 + 660 + 700 = 1,800 kcal.
PLAN = Plan(
    (
        Meal(0, B, 10, 2),
        Meal(0, L, 22, 2),
        Meal(0, D, 20, 2),
        Meal(1, B, 11, 2),
        Meal(1, L, 21, 2),
        Meal(1, D, 20, 2),
    )
)


def put(plan: Plan, *meals: Meal) -> Plan:
    """Replace the meals at the given (day, slot)s, or add them."""
    keys = {(m.day, m.slot) for m in meals}
    return Plan(tuple(m for m in plan.meals if (m.day, m.slot) not in keys) + meals)


def drop(plan: Plan, day: int, slot: Slot) -> Plan:
    return Plan(tuple(m for m in plan.meals if (m.day, m.slot) != (day, slot)))


def codes(problem: Problem, plan: Plan) -> set[Code]:
    return {v.code for v in validate(problem, plan)}


def test_base_plan_is_valid() -> None:
    assert validate(BASE, PLAN) == []


type Mutation = Callable[[Problem, Plan], tuple[Problem, Plan]]

MUTATIONS: dict[Code, Mutation] = {
    Code.DAY_RANGE: lambda p, plan: (p, Plan((*plan.meals, Meal(2, S, 30, 1)))),
    Code.UNKNOWN_SLOT: lambda p, plan: (
        replace(p, slots=p.slots[:3]),
        Plan((*plan.meals, Meal(0, S, 30, 1))),
    ),
    Code.DUPLICATE: lambda p, plan: (p, Plan((*plan.meals, Meal(0, L, 21, 1)))),
    Code.MISSING: lambda p, plan: (p, drop(plan, 1, B)),
    Code.UNKNOWN_RECIPE: lambda p, plan: (p, put(plan, Meal(0, S, 999, 1))),
    Code.NOT_ELIGIBLE: lambda p, plan: (p, put(plan, Meal(0, B, 21, 1))),
    Code.PORTIONS: lambda p, plan: (p, put(plan, Meal(0, L, 22, 5))),
    Code.ALLERGEN: lambda p, plan: (p, put(plan, Meal(0, D, 40, 2))),
    Code.UNVERIFIED: lambda p, plan: (p, put(plan, Meal(0, D, 43, 2))),
    Code.AVOIDED: lambda p, plan: (p, put(plan, Meal(0, D, 42, 2))),
    Code.DIET: lambda p, plan: (p, put(plan, Meal(0, D, 41, 2))),
    Code.UNKNOWN_FOOD: lambda p, plan: (p, put(plan, Meal(0, D, 44, 2))),
    Code.LOCKED: lambda p, plan: (replace(p, locked={(0, L): Meal(0, L, 21, 2)}), plan),
    Code.REPEATS: lambda p, plan: (p, put(plan, Meal(0, L, 20, 2))),
    Code.CALORIE_FLOOR: lambda p, plan: (
        replace(p, targets=replace(p.targets, daily={Nutrient.KCAL: Band(1000, 2000)})),
        put(plan, Meal(0, B, 10, 1), Meal(0, L, 22, 1)),
    ),
    Code.DAILY_BAND: lambda p, plan: (p, put(plan, Meal(1, D, 20, 4))),
    Code.WEEKLY_BAND: lambda p, plan: (
        replace(p, targets=replace(p.targets, weekly={Nutrient.KCAL: Band(None, 3000)})),
        plan,
    ),
    Code.BUDGET: lambda p, plan: (replace(p, budget=1), plan),
}


def test_every_code_has_a_mutation() -> None:
    assert set(MUTATIONS) == set(Code)


@pytest.mark.parametrize("code", list(Code))
def test_each_mutation_produces_exactly_its_code(code: Code) -> None:
    problem, plan = MUTATIONS[code](BASE, PLAN)
    violations = validate(problem, plan)
    assert {v.code for v in violations} == {code}
    assert all(v.hard for v in violations)


def test_code_sets() -> None:
    assert {
        Code.ALLERGEN,
        Code.UNVERIFIED,
        Code.AVOIDED,
        Code.DIET,
        Code.UNKNOWN_FOOD,
        Code.CALORIE_FLOOR,
    } == SAFETY_CODES
    assert {
        Code.DAY_RANGE,
        Code.UNKNOWN_SLOT,
        Code.DUPLICATE,
        Code.MISSING,
        Code.UNKNOWN_RECIPE,
        Code.NOT_ELIGIBLE,
        Code.PORTIONS,
        Code.LOCKED,
    } == STRUCTURAL_CODES
    assert SAFETY_CODES - {Code.CALORIE_FLOOR} == HARD_FILTER_CODES


def test_text_allergens_count() -> None:
    assert codes(BASE, put(PLAN, Meal(1, D, 45, 2))) == {Code.ALLERGEN}


def test_allergen_message_lists_every_hit() -> None:
    kiwi = cast(Allergen, "kiwi")  # not one of the 14: still matched, never a crash
    nuts = frozenset({Allergen.TREE_NUTS, Allergen.MILK, kiwi})
    curry = replace(RECIPES[40], id=46, text_allergens=nuts)
    p = replace(
        BASE,
        recipes={**RECIPES, 46: curry},
        profile=Profile(allergens=frozenset({Allergen.PEANUTS, Allergen.TREE_NUTS, kiwi})),
    )
    found = validate(p, put(PLAN, Meal(0, D, 46, 2)))
    assert [v.message for v in found] == [
        "Mon dinner: Thai green curry contains tree nuts, peanuts and kiwi"
    ]


def test_unverified_recipes_are_fine_without_restrictions() -> None:
    open_profile = replace(BASE, profile=Profile())
    assert validate(open_profile, put(PLAN, Meal(0, D, 43, 2))) == []
    # Unknown foods are never fine: nothing is known about them.
    assert codes(open_profile, put(PLAN, Meal(0, D, 44, 2))) == {Code.UNKNOWN_FOOD}


# --- locks -------------------------------------------------------------------------------------


def test_locked_meals_skip_eligibility_and_portions_but_count_toward_nutrition() -> None:
    lock = Meal(0, B, 21, 6)  # not a breakfast, and more portions than breakfast allows
    p = replace(BASE, locked={(0, B): lock})
    found = codes(p, put(PLAN, lock))
    assert Code.NOT_ELIGIBLE not in found
    assert Code.PORTIONS not in found
    assert Code.LOCKED not in found
    assert found == {Code.DAILY_BAND}  # Mon 1,980 + 360 + 700 kcal


def test_locked_meals_still_get_hard_filters() -> None:
    lock = Meal(0, D, 40, 2)
    p = replace(BASE, locked={(0, D): lock})
    assert codes(p, put(PLAN, lock)) == {Code.ALLERGEN}


def test_slot_locked_empty() -> None:
    p = replace(BASE, locked={(1, B): None})
    assert validate(p, drop(PLAN, 1, B)) == []
    found = validate(p, PLAN)
    assert [(v.code, v.day, v.slot, v.recipe_id) for v in found] == [(Code.LOCKED, 1, B, 11)]


def test_slot_locked_to_a_meal_that_is_missing() -> None:
    p = replace(BASE, locked={(1, B): Meal(1, B, 11, 2)})
    assert codes(p, drop(PLAN, 1, B)) == {Code.LOCKED}  # not also MISSING
    assert codes(p, put(PLAN, Meal(1, B, 11, 1))) == {Code.LOCKED}  # portions must match too


def test_repeats_need_an_unlocked_meal() -> None:
    plan = put(PLAN, Meal(0, L, 20, 2))  # risotto 3 times, cap 2
    all_locked = {(m.day, m.slot): m for m in plan.meals if m.recipe_id == 20}
    assert Code.REPEATS not in codes(replace(BASE, locked=all_locked), plan)
    some_locked = {k: m for k, m in all_locked.items() if k != (0, L)}
    assert Code.REPEATS in codes(replace(BASE, locked=some_locked), plan)


# --- flags, order, messages ----------------------------------------------------------------------


def test_macro_bands_are_soft_kcal_is_hard() -> None:
    targets = replace(
        BASE.targets,
        daily={Nutrient.KCAL: Band(1500, 2000), Nutrient.PROTEIN: Band(65, None)},
        weekly={Nutrient.PROTEIN: Band(None, 50), Nutrient.KCAL: Band(4000, None)},
    )
    found = validate(replace(BASE, targets=targets), PLAN)
    assert [(v.code, v.day, v.hard) for v in found] == [
        (Code.DAILY_BAND, 0, True),  # Mon 1,460 kcal
        (Code.DAILY_BAND, 0, False),  # Mon 46 g protein
        (Code.DAILY_BAND, 1, False),  # Tue 60 g protein
        (Code.WEEKLY_BAND, None, True),
        (Code.WEEKLY_BAND, None, False),
    ]
    assert hard(found) == [found[0], found[3]]
    assert found[1].message == "Mon: 46 g protein is below your 65 g minimum"
    assert found[3].message == "Whole plan: 3,260 kcal is below your 4,000 kcal minimum"


def test_messages_use_weekday_names() -> None:
    p = replace(BASE, targets=replace(BASE.targets, daily={}))
    plan = put(PLAN, Meal(1, B, 10, 1), Meal(1, L, 22, 1), Meal(1, D, 40, 2))
    found = validate(p, plan)
    assert [v.message for v in found] == [
        "Tue dinner: Thai green curry contains peanuts",
        "Tue: 1,080 kcal is below your 1,200 kcal floor",
    ]
    assert [(v.day, v.slot, v.recipe_id) for v in found] == [(1, D, 40), (1, None, None)]


def test_long_plans_add_the_date() -> None:
    p = replace(BASE, days=14, slots=(), targets=Targets(daily={}, calorie_floor=0))
    plan = Plan((Meal(8, D, 40, 2),))
    assert [v.message for v in validate(p, plan)] == [
        "Tue 13 Jan dinner: Thai green curry is in a slot this plan doesn't have",
        "Tue 13 Jan dinner: Thai green curry contains peanuts",
    ]


def test_messages_name_the_cause() -> None:
    def message(code: Code) -> str:
        problem, plan = MUTATIONS[code](BASE, PLAN)
        (v,) = validate(problem, plan)
        return v.message

    assert message(Code.DIET) == "Mon dinner: Beef stew isn't vegetarian (meat)"
    assert (
        message(Code.AVOIDED) == "Mon dinner: Coriander salad contains coriander, which you avoid"
    )
    assert message(Code.REPEATS) == "Vegetable risotto is planned 3 times; the limit is 2"
    assert message(Code.MISSING) == "Tue breakfast: no meal planned"
    assert message(Code.PORTIONS) == "Mon lunch: 5 portions of Lentil soup; allowed 1 to 4"
    assert message(Code.BUDGET) == "Estimated shopping cost 2.18 is over your 0.01 budget"


def test_order_is_day_then_slot_then_code() -> None:
    p = replace(BASE, budget=1, locked={(1, S): None})
    plan = Plan(
        (
            Meal(1, S, 40, 1),
            Meal(1, D, 41, 9),
            Meal(0, D, 40, 1),
            Meal(0, B, 21, 1),
            Meal(0, B, 10, 1),
            Meal(5, L, 999, 1),
        )
    )
    found = validate(p, plan)
    code_rank = {c: i for i, c in enumerate(Code)}
    keys = [
        (
            v.day is None,
            v.day or 0,
            SLOT_ORDER.index(v.slot) if v.slot is not None else len(SLOT_ORDER),
            code_rank[v.code],
        )
        for v in found
    ]
    assert keys == sorted(keys)
    assert found[-1].code == Code.BUDGET
    assert validate(p, plan) == found  # deterministic


def test_identical_occurrences_are_reported_once() -> None:
    meal = Meal(0, D, 40, 2)
    found = [v.code for v in validate(BASE, Plan((*put(PLAN, meal).meals, meal)))]
    assert found.count(Code.DUPLICATE) == found.count(Code.ALLERGEN) == 1


# --- malformed plans -----------------------------------------------------------------------------


def test_malformed_plans_are_reported_not_raised() -> None:
    plan = Plan(
        (
            Meal(-1, B, 10, 1),
            Meal(0, cast(Slot, "brunch"), 10, 1),
            Meal(0, L, 12345, 0),
            Meal(0, D, 20, -3),
        )
    )
    found = validate(BASE, plan)
    assert {Code.DAY_RANGE, Code.UNKNOWN_SLOT, Code.UNKNOWN_RECIPE, Code.PORTIONS} <= {
        v.code for v in found
    }
    assert all(isinstance(v, Violation) for v in found)


meals = st.builds(
    Meal,
    day=st.integers(-2, 4),
    slot=st.sampled_from([*Slot, cast(Slot, "brunch")]),
    recipe_id=st.sampled_from([*RECIPES, 999]),
    portions=st.integers(-1, 6),
)
locks = st.dictionaries(
    st.tuples(st.integers(0, 1), st.sampled_from(Slot)),
    st.none() | st.builds(Meal, st.just(0), st.just(B), st.sampled_from([10, 40, 999]), st.just(2)),
    max_size=3,
)


@given(st.lists(meals, max_size=10), locks, st.none() | st.integers(0, 2000))
def test_validate_never_raises(
    plan_meals: list[Meal], locked: dict[tuple[int, Slot], Meal | None], budget: int | None
) -> None:
    p = replace(BASE, locked=locked, budget=budget)
    plan = Plan(tuple(plan_meals))
    found = validate(p, plan)
    assert found == validate(p, plan)
    found_codes = {v.code for v in found}
    if any(m.recipe_id == 999 for m in plan_meals):
        assert Code.UNKNOWN_RECIPE in found_codes
    if any(not 0 <= m.day < p.days for m in plan_meals):
        assert Code.DAY_RANGE in found_codes
    if any(m.slot not in Slot for m in plan_meals):
        assert Code.UNKNOWN_SLOT in found_codes
    for v in found:
        assert v.hard or v.code in {Code.DAILY_BAND, Code.WEEKLY_BAND}
        assert v.message


# --- scenarios and independence ------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(50))
def test_planted_witnesses_have_no_hard_violations(seed: int) -> None:
    s = planted(seed)
    assert s.witness is not None
    assert hard(validate(s.problem, s.witness)) == []


def imports(module: str) -> set[str]:
    """The larder_solver modules `module` imports directly."""
    source = cast(str, importlib.import_module(module).__file__)
    imported: set[str] = set()
    for node in ast.walk(ast.parse(Path(source).read_text())):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            imported.add(node.module or "")
    return {name for name in imported if name.split(".")[0] == "larder_solver"}


def test_validator_imports_only_problem_and_metrics() -> None:
    # Not the planners, the prefilter (whose hard filters it re-implements), the scenarios or
    # the diagnostics; and metrics, which it does use, imports only the problem.
    assert imports("larder_solver.validate") <= {"larder_solver.metrics", "larder_solver.problem"}
    assert imports("larder_solver.metrics") <= {"larder_solver.problem"}
    assert imports("larder_solver.problem") == set()
