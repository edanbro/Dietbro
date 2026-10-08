import pytest
from hypothesis import given
from hypothesis import strategies as st

from larder_core.nutrition import Nutrients, estimate_servings, for_grams, total

values = st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False)
nutrients = st.builds(
    Nutrients,
    kcal=values,
    protein_g=values,
    fat_g=values,
    carbs_g=values,
    fiber_g=values,
    sugars_g=values,
    sat_fat_g=values,
    sodium_mg=values,
)
grams = st.floats(min_value=0, max_value=5000, allow_nan=False, allow_infinity=False)


def test_for_grams_scales_per_100g() -> None:
    butter = Nutrients(kcal=717, protein_g=0.85, fat_g=81.1, carbs_g=0.06)

    n = for_grams(butter, 50)

    assert n.kcal == pytest.approx(358.5)
    assert n.fat_g == pytest.approx(40.55)


def test_total_sums_ingredients() -> None:
    rice = Nutrients(kcal=365, protein_g=7.1, carbs_g=80)
    oil = Nutrients(kcal=884, fat_g=100)

    n = total([(rice, 200), (oil, 15)])

    assert n.kcal == pytest.approx(730 + 132.6)
    assert n.fat_g == pytest.approx(15)


@given(nutrients, grams, grams)
def test_scaling_is_additive_in_grams(n: Nutrients, g1: float, g2: float) -> None:
    combined = for_grams(n, g1 + g2)
    split = for_grams(n, g1) + for_grams(n, g2)
    for field in Nutrients.FIELDS:
        assert getattr(combined, field) == pytest.approx(getattr(split, field), rel=1e-9, abs=1e-9)


@given(st.lists(st.tuples(nutrients, grams), max_size=10))
def test_total_is_order_independent(items: list[tuple[Nutrients, float]]) -> None:
    forward = total(items)
    backward = total(reversed(items))
    for field in Nutrients.FIELDS:
        assert getattr(forward, field) == pytest.approx(
            getattr(backward, field), rel=1e-9, abs=1e-6
        )


@given(nutrients, st.integers(min_value=1, max_value=12))
def test_per_serving_times_servings_is_total(n: Nutrients, servings: int) -> None:
    per = n.per_serving(servings)
    for field in Nutrients.FIELDS:
        assert getattr(per, field) * servings == pytest.approx(getattr(n, field), abs=1e-9)


def test_per_serving_rejects_zero() -> None:
    with pytest.raises(ValueError, match="servings"):
        Nutrients(kcal=100).per_serving(0)


@pytest.mark.parametrize(
    ("kcal", "expected"),
    [(0, 1), (300, 1), (1300, 2), (2600, 4), (3900, 6), (20000, 8)],
)
def test_estimate_servings(kcal: float, expected: int) -> None:
    assert estimate_servings(kcal) == expected


@given(st.floats(min_value=0, max_value=1e6), st.floats(min_value=0, max_value=1e6))
def test_estimate_servings_is_monotonic_and_bounded(a: float, b: float) -> None:
    lo, hi = sorted((a, b))
    assert 1 <= estimate_servings(lo) <= estimate_servings(hi) <= 8
