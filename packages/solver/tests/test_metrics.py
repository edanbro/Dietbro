from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from larder_solver.metrics import (
    allocate,
    changed_slots,
    cost_millipence,
    day_totals,
    macro_distance,
    repeat_counts,
    score,
    staples,
    to_minor,
    usage,
    waste_millipence,
    week_totals,
)
from larder_solver.problem import (
    Band,
    Food,
    Ingredient,
    Lot,
    Macros,
    Meal,
    Nutrient,
    Plan,
    Problem,
    Recipe,
    Slot,
    SlotSpec,
    Targets,
)

B, L, D, S = Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER, Slot.SNACK
MACROS = Macros(300, 20, 10, 30)
SLOTS = (
    SlotSpec(B, True, ()),
    SlotSpec(L, True, ()),
    SlotSpec(D, True, ()),
    SlotSpec(S, False, ()),
)


def recipe(
    rid: int,
    *ingredients: tuple[int, int],
    macros: Macros = MACROS,
    preference: int = 0,
) -> Recipe:
    return Recipe(
        id=rid,
        name=f"Recipe {rid}",
        meal_types=frozenset(Slot),
        per_portion=macros,
        ingredients=tuple(Ingredient(f, g) for f, g in ingredients),
        preference=preference,
    )


def problem(
    recipes: Sequence[Recipe],
    prices: Mapping[int, int],
    *,
    days: int = 3,
    pantry: Sequence[Lot] = (),
    targets: Targets | None = None,
    extra: Mapping[int, Macros] | None = None,
) -> Problem:
    return Problem(
        start=date(2026, 1, 5),
        days=days,
        slots=SLOTS,
        recipes={r.id: r for r in recipes},
        foods={f: Food(f, f"Food {f}", price_per_kg=p) for f, p in prices.items()},
        targets=targets or Targets(daily={}),
        pantry=tuple(pantry),
        extra=extra or {},
    )


# --- nutrition ---------------------------------------------------------------------------------


def test_day_totals_sum_meals_and_extra() -> None:
    p = problem(
        [recipe(1, macros=Macros(100, 10, 5, 12)), recipe(2, macros=Macros(250, 20, 8, 30))],
        {},
        extra={1: Macros(500, 1, 2, 3)},
    )
    plan = Plan((Meal(0, B, 1, 2), Meal(0, L, 2, 1), Meal(1, D, 2, 3)))
    assert day_totals(p, plan) == [
        Macros(450, 40, 18, 54),
        Macros(1250, 61, 26, 93),
        Macros(),
    ]
    assert week_totals(p, plan) == Macros(1700, 101, 44, 147)


def test_unknown_recipes_and_days_outside_the_horizon_are_skipped() -> None:
    p = problem([recipe(1, (7, 50))], {7: 1000})
    plan = Plan((Meal(0, B, 1, 1), Meal(0, L, 99, 2), Meal(5, D, 1, 1), Meal(-1, D, 1, 1)))
    assert day_totals(p, plan) == [Macros(300, 20, 10, 30), Macros(), Macros()]
    assert usage(p, plan) == {7: [50, 0, 0]}
    assert allocate(p, plan).buy == {7: 50}
    assert score(p, plan).terms["repeat"] < 0  # recipe 1 counted three times, 99 once


def test_usage_is_grams_times_portions_per_day() -> None:
    p = problem([recipe(1, (7, 30), (8, 0)), recipe(2, (7, 10), (9, 5))], {7: 1, 8: 1, 9: 1})
    plan = Plan((Meal(0, B, 1, 2), Meal(0, L, 2, 3), Meal(2, D, 1, 1)))
    assert usage(p, plan) == {7: [90, 0, 30], 9: [15, 0, 0]}  # 0 g staples use nothing


def test_usage_skips_foods_missing_from_the_problem() -> None:
    p = problem([recipe(1, (7, 30), (404, 20))], {7: 100})
    assert usage(p, Plan((Meal(0, B, 1, 1),))) == {7: [30, 0, 0]}


# --- pantry allocation (earliest deadline first) -----------------------------------------------


def eat(grams_by_day: Mapping[int, int], food: int = 7) -> tuple[list[Recipe], Plan]:
    """One meal per listed day using `grams` of `food`."""
    recipes = [recipe(100 + d, (food, g)) for d, g in grams_by_day.items()]
    return recipes, Plan(tuple(Meal(d, L, 100 + d, 1) for d in grams_by_day))


def test_edf_uses_the_lot_expiring_first() -> None:
    recipes, plan = eat({0: 100})
    p = problem(recipes, {7: 1000}, pantry=[Lot(7, 100, expires=3), Lot(7, 100, expires=1)])
    a = allocate(p, plan)
    assert a.pantry_used == {7: 100}
    assert a.buy == {}
    assert a.waste == {}  # the day-1 lot was used; the other keeps past the 3-day horizon


def test_edf_uses_lots_without_expiry_last() -> None:
    recipes, plan = eat({0: 100})
    p = problem(recipes, {7: 1000}, pantry=[Lot(7, 100), Lot(7, 100, expires=2)])
    a = allocate(p, plan)
    assert (a.pantry_used, a.buy, a.waste) == ({7: 100}, {}, {})


def test_expired_lots_are_ignored_and_not_waste() -> None:
    recipes, plan = eat({0: 100})
    p = problem(recipes, {7: 1000}, pantry=[Lot(7, 500, expires=-1)])
    a = allocate(p, plan)
    assert (a.pantry_used, a.buy, a.waste) == ({}, {7: 100}, {})


def test_partial_lot_then_buy() -> None:
    recipes, plan = eat({0: 100})
    p = problem(recipes, {7: 1000}, pantry=[Lot(7, 60)])
    a = allocate(p, plan)
    assert (a.pantry_used, a.buy, a.waste) == ({7: 60}, {7: 40}, {})


def test_lot_is_usable_through_its_expiry_day_only() -> None:
    recipes, plan = eat({0: 30, 1: 50})
    p = problem(recipes, {7: 1000}, pantry=[Lot(7, 100, expires=0)])
    a = allocate(p, plan)
    assert (a.pantry_used, a.buy, a.waste) == ({7: 30}, {7: 50}, {7: 70})


def test_edf_across_days() -> None:
    recipes, plan = eat({0: 50, 1: 50, 2: 50})
    p = problem(recipes, {7: 1000}, pantry=[Lot(7, 100), Lot(7, 100, expires=1)])
    a = allocate(p, plan)
    assert (a.pantry_used, a.buy, a.waste) == ({7: 150}, {}, {})


@pytest.mark.parametrize(("expires", "waste"), [(None, {}), (3, {}), (2, {7: 100}), (0, {7: 100})])
def test_waste_is_in_horizon_leftovers(expires: int | None, waste: dict[int, int]) -> None:
    p = problem([], {7: 1000}, pantry=[Lot(7, 100, expires=expires)])
    assert allocate(p, Plan(())).waste == waste


def test_staples_are_never_drawn_or_bought() -> None:
    p = problem([recipe(1, (7, 0), (8, 20))], {7: 500, 8: 100}, pantry=[Lot(7, 100, expires=0)])
    plan = Plan((Meal(0, L, 1, 2),))
    a = allocate(p, plan)
    assert (a.pantry_used, a.buy, a.waste) == ({}, {8: 40}, {7: 100})
    assert staples(p, plan) == {7}


lots = st.builds(
    Lot,
    food_id=st.integers(1, 3),
    grams=st.integers(0, 400),
    expires=st.none() | st.integers(-2, 5),
)
meals = st.builds(
    Meal,
    day=st.integers(0, 3),
    slot=st.sampled_from(Slot),
    recipe_id=st.integers(1, 3),
    portions=st.integers(1, 4),
)


@given(st.lists(lots, max_size=6), st.lists(meals, max_size=8))
def test_allocation_conserves_grams(pantry: list[Lot], plan_meals: list[Meal]) -> None:
    recipes = [recipe(1, (1, 50), (2, 20)), recipe(2, (2, 80)), recipe(3, (3, 10), (1, 0))]
    p = problem(recipes, {1: 100, 2: 200, 3: 300}, days=4, pantry=pantry)
    plan = Plan(tuple(plan_meals))
    a = allocate(p, plan)
    need = {f: sum(per_day) for f, per_day in usage(p, plan).items()}
    usable = Counter[int]()
    for lot in pantry:
        if lot.expires is None or lot.expires >= 0:
            usable[lot.food_id] += lot.grams
    for f in {1, 2, 3}:
        assert a.pantry_used.get(f, 0) + a.buy.get(f, 0) == need.get(f, 0)
        assert a.pantry_used.get(f, 0) + a.waste.get(f, 0) <= usable[f]
    assert all(v > 0 for d in (a.buy, a.pantry_used, a.waste) for v in d.values())
    if all(lot.expires is None for lot in pantry):  # no deadlines: buy only the shortfall
        for f in {1, 2, 3}:
            assert a.buy.get(f, 0) == max(0, need.get(f, 0) - usable[f])


# --- money ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("millipence", "minor"),
    [(0, 0), (1, 1), (999, 1), (1000, 1), (1001, 2), (2_500_000, 2500), (2_500_001, 2501)],
)
def test_to_minor_rounds_up(millipence: int, minor: int) -> None:
    assert to_minor(millipence) == minor


def test_cost_and_waste_are_grams_times_price_per_kg() -> None:
    p = problem([], {1: 1000, 2: 2999})
    assert cost_millipence(p, {1: 250, 2: 3}) == 250 * 1000 + 3 * 2999
    assert to_minor(cost_millipence(p, {1: 250, 2: 3})) == 259
    assert waste_millipence(p, {2: 10}) == 29_990
    assert cost_millipence(p, {404: 1000}) == 0  # unknown foods are skipped


# --- repeats, churn, macros, staples -----------------------------------------------------------


def test_repeat_counts_every_meal() -> None:
    plan = Plan((Meal(0, B, 1, 1), Meal(1, B, 1, 2), Meal(1, L, 2, 1)))
    assert repeat_counts(plan) == Counter({1: 2, 2: 1})


def test_changed_slots_counts_recipe_and_presence_changes_not_portions() -> None:
    before = Plan((Meal(0, B, 1, 2), Meal(0, L, 3, 1), Meal(1, L, 2, 1), Meal(1, S, 3, 1)))
    after = Plan((Meal(0, B, 1, 1), Meal(0, L, 2, 2), Meal(1, B, 1, 1), Meal(1, L, 2, 3)))
    # (0, L) recipe changed; (1, B) added; (1, S) dropped; portions alone don't count.
    assert changed_slots(before, after) == 3
    assert changed_slots(after, after) == 0
    assert changed_slots(None, after) == 0


def test_macro_distance_counts_soft_daily_and_weekly_bands_only() -> None:
    targets = Targets(
        daily={
            Nutrient.KCAL: Band(5000, 6000),  # hard: never part of the soft distance
            Nutrient.PROTEIN: Band(50, None),
            Nutrient.FAT: Band(None, 20),
        },
        weekly={Nutrient.PROTEIN: Band(None, 100), Nutrient.KCAL: Band(0, 1)},
    )
    p = problem([recipe(1, macros=Macros(100, 30, 15, 0))], {}, days=2, targets=targets)
    plan = Plan((Meal(0, L, 1, 2), Meal(1, L, 1, 1)))
    # day 0: protein 60 ok, fat 30 (+10); day 1: protein 30 (+20), fat 15 ok; week protein 90 ok.
    assert macro_distance(p, plan) == 30
    plan = Plan((Meal(0, L, 1, 3), Meal(1, L, 1, 1)))
    # day 0: fat 45 (+25); day 1: +20; week protein 120 (+20).
    assert macro_distance(p, plan) == 65


def test_staples_are_foods_only_ever_used_at_zero_grams() -> None:
    p = problem([recipe(1, (4, 0), (5, 0), (404, 0)), recipe(2, (4, 10))], {4: 1, 5: 1})
    assert staples(p, Plan((Meal(0, L, 1, 1),))) == {4, 5}
    assert staples(p, Plan((Meal(0, L, 1, 1), Meal(0, D, 2, 1)))) == {5}


# --- score ---------------------------------------------------------------------------------------


def test_score_terms_on_a_hand_case() -> None:
    recipes = [
        recipe(1, (1, 100), macros=Macros(200, 10, 5, 30), preference=10),
        recipe(2, (2, 50), macros=Macros(400, 30, 10, 40), preference=-5),
        recipe(3, (3, 20), macros=Macros(100, 2, 1, 15)),
    ]
    targets = Targets(
        daily={Nutrient.KCAL: Band(0, 100), Nutrient.PROTEIN: Band(50, None)},
        weekly={Nutrient.PROTEIN: Band(None, 100)},
    )
    p = problem(
        recipes,
        {1: 2000, 2: 1000, 3: 500},
        days=2,
        targets=targets,
        pantry=[Lot(1, 150, expires=1), Lot(3, 40, expires=0)],
    )
    plan = Plan(
        (
            Meal(0, B, 1, 1),
            Meal(0, L, 2, 2),
            Meal(1, B, 1, 1),
            Meal(1, L, 2, 1),
            Meal(1, S, 3, 1),
        )
    )
    previous = Plan((Meal(0, B, 1, 2), Meal(0, L, 3, 1), Meal(1, L, 2, 1), Meal(1, S, 3, 1)))
    s = score(p, plan, previous)
    assert s.terms == {
        "preference": 1_000 * (10 - 5 + 10 - 5 + 0),
        "pantry": 100 * 150,  # food 1: 100 g on day 0 + 50 g on day 1
        "cost": -(50 * 2000 + 150 * 1000 + 20 * 500),  # food 3's lot expired before day 1
        "waste": -2 * (40 * 500),
        "repeat": -150_000 * 2,  # recipes 1 and 2 twice each
        "optional": -120_000 * 1,  # one snack
        "macro": -20_000 * (8 + 12),  # day 1 protein 42 < 50; week protein 112 > 100
        "churn": -200_000 * 2,  # (0, L) changed recipe, (1, B) is new
    }
    assert list(s.terms) == [
        "preference",
        "pantry",
        "cost",
        "waste",
        "repeat",
        "optional",
        "macro",
        "churn",
    ]
    assert s.total == sum(s.terms.values()) == -1_495_000
    assert score(p, plan).terms["churn"] == 0


def test_score_counts_meals_in_slots_without_a_spec_as_optional() -> None:
    p = problem([recipe(1)], {})
    p = Problem(
        start=p.start,
        days=p.days,
        slots=(SlotSpec(L, True, ()),),
        recipes=p.recipes,
        foods=p.foods,
        targets=p.targets,
    )
    plan = Plan((Meal(0, L, 1, 1), Meal(0, S, 1, 1), Meal(1, B, 1, 1)))
    assert score(p, plan).terms["optional"] == -120_000 * 2
