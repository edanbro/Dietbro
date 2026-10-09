from collections.abc import Sequence
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from larder_solver.metrics import allocate, cost_millipence, to_minor
from larder_solver.problem import (
    Food,
    Ingredient,
    Lot,
    Macros,
    Meal,
    Plan,
    Problem,
    Recipe,
    Slot,
    SlotSpec,
    Targets,
)
from larder_solver.scenarios import planted
from larder_solver.shopping import ShoppingLine, shopping_list


def problem(
    foods: Sequence[Food], ingredients: Sequence[tuple[int, int]], pantry: Sequence[Lot] = ()
) -> tuple[Problem, Plan]:
    """A one-day problem whose single lunch uses `ingredients` (food id, grams)."""
    r = Recipe(
        1,
        "Stew",
        frozenset({Slot.LUNCH}),
        Macros(500, 20, 20, 50),
        tuple(Ingredient(f, g) for f, g in ingredients),
    )
    p = Problem(
        start=date(2026, 1, 5),
        days=1,
        slots=(SlotSpec(Slot.LUNCH, True, (1,)),),
        recipes={1: r},
        foods={f.id: f for f in foods},
        targets=Targets(daily={}),
        pantry=tuple(pantry),
    )
    return p, Plan((Meal(0, Slot.LUNCH, 1, 1),))


def test_lines_sum_to_the_plan_cost_by_largest_remainder() -> None:
    foods = [
        Food(1, "a", price_per_kg=15),
        Food(2, "b", price_per_kg=15),
        Food(3, "c", price_per_kg=10),
    ]
    p, plan = problem(foods, [(1, 100), (2, 100), (3, 100)])
    s = shopping_list(p, plan)
    assert s.total_minor == 4  # ceil(4,000 millipence / 1000)
    # 1.5p, 1.5p, 1p: floors 1 + 1 + 1, the spare penny goes to the lower food id on a tie.
    assert [(line.food_id, line.cost_millipence, line.cost_minor) for line in s.lines] == [
        (1, 1500, 2),
        (2, 1500, 1),
        (3, 1000, 1),
    ]


def test_largest_remainders_win_the_spare_pennies() -> None:
    foods = [
        Food(1, "a", price_per_kg=4),
        Food(2, "b", price_per_kg=4),
        Food(3, "c", price_per_kg=7),
    ]
    p, plan = problem(foods, [(1, 100), (2, 100), (3, 100)])
    s = shopping_list(p, plan)
    assert s.total_minor == 2  # ceil(1,500 / 1000)
    assert {line.food_id: line.cost_minor for line in s.lines} == {1: 1, 2: 0, 3: 1}


def test_staples_are_listed_last_without_grams_or_cost() -> None:
    foods = [
        Food(1, "salt", "Spices and Herbs"),
        Food(2, "pepper", None),
        Food(3, "rice", "Cereal Grains and Pasta", price_per_kg=300),
    ]
    p, plan = problem(foods, [(1, 0), (2, 0), (3, 75)])
    s = shopping_list(p, plan)
    assert s.lines == (
        ShoppingLine(3, 75, 22_500, 23, staple=False),
        ShoppingLine(2, 0, 0, 0, staple=True),
        ShoppingLine(1, 0, 0, 0, staple=True),
    )
    assert s.total_minor == 23


def test_order_is_category_then_name_then_id() -> None:
    foods = [
        Food(1, "milk", "Dairy", price_per_kg=100),
        Food(2, "Butter", "Dairy", price_per_kg=100),
        Food(3, "banana", None, price_per_kg=100),
        Food(4, "bread", "Baked", price_per_kg=100),
        Food(5, "bread", "Baked", price_per_kg=100),
    ]
    p, plan = problem(foods, [(f.id, 10) for f in foods])
    assert [line.food_id for line in shopping_list(p, plan).lines] == [3, 4, 5, 2, 1]


def test_foods_fully_covered_by_the_pantry_are_not_bought() -> None:
    foods = [Food(1, "rice", price_per_kg=300), Food(2, "beans", price_per_kg=400)]
    p, plan = problem(foods, [(1, 100), (2, 100)], pantry=[Lot(1, 500), Lot(2, 40)])
    s = shopping_list(p, plan)
    assert [(line.food_id, line.grams) for line in s.lines] == [(2, 60)]
    assert s.total_minor == to_minor(60 * 400) == 24


@given(st.lists(st.tuples(st.integers(1, 2000), st.integers(0, 5000)), min_size=1, max_size=12))
def test_lines_always_sum_to_the_total(lines: list[tuple[int, int]]) -> None:
    foods = [Food(i, f"food {i}", price_per_kg=price) for i, (_, price) in enumerate(lines)]
    p, plan = problem(foods, [(i, grams) for i, (grams, _) in enumerate(lines)])
    s = shopping_list(p, plan)
    millipence = cost_millipence(p, allocate(p, plan).buy)
    assert s.total_minor == to_minor(millipence)
    assert sum(line.cost_minor for line in s.lines) == s.total_minor
    assert sum(line.cost_millipence for line in s.lines) == millipence
    for line in s.lines:
        assert abs(line.cost_minor * 1000 - line.cost_millipence) < 1000


@pytest.mark.parametrize("seed", range(5))
def test_planted_witness_shopping_list(seed: int) -> None:
    s = planted(seed)
    assert s.witness is not None
    shop = shopping_list(s.problem, s.witness)
    bought = allocate(s.problem, s.witness).buy
    assert {line.food_id: line.grams for line in shop.lines if not line.staple} == bought
    assert shop.total_minor == to_minor(cost_millipence(s.problem, bought))
    assert sum(line.cost_minor for line in shop.lines) == shop.total_minor
    staple_lines = [line for line in shop.lines if line.staple]
    assert all(line.grams == line.cost_minor == line.cost_millipence == 0 for line in staple_lines)
    assert shop.lines[: len(shop.lines) - len(staple_lines)] == tuple(
        line for line in shop.lines if not line.staple
    )
