import math
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from larder_core.units import (
    COUNT_UNITS,
    MASS_UNITS,
    VOLUME_UNITS,
    Dimension,
    Measure,
    canonical_unit,
    convert,
    parse_measure,
    parse_quantity,
)

# --- unit table -------------------------------------------------------------------------------


def test_unit_table_is_internally_consistent() -> None:
    assert convert(1, "kg", "g") == 1000
    assert convert(1, "lb", "oz") == pytest.approx(16)
    assert convert(1, "tbsp", "tsp") == pytest.approx(3)
    assert convert(1, "cup", "tbsp") == pytest.approx(16)
    assert convert(1, "l", "ml") == 1000


def test_convert_rejects_cross_dimension() -> None:
    with pytest.raises(ValueError, match="mass"):
        convert(1, "g", "ml")


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("g", "g"),
        ("grams", "g"),
        ("Tablespoons", "tbsp"),
        ("tbs", "tbsp"),
        ("tblsp", "tbsp"),
        ("tsp.", "tsp"),
        ("cups", "cup"),
        ("lbs", "lb"),
        ("ounces", "oz"),
        ("litres", "l"),
        ("cloves", "clove"),
        ("unknown-word", None),
    ],
)
def test_canonical_unit(word: str, expected: str | None) -> None:
    assert canonical_unit(word) == expected


mass_units = st.sampled_from(sorted(MASS_UNITS))
volume_units = st.sampled_from(sorted(VOLUME_UNITS))
amounts = st.floats(min_value=1e-3, max_value=1e5, allow_nan=False, allow_infinity=False)


@given(amounts, mass_units, mass_units)
def test_mass_conversion_round_trips(q: float, a: str, b: str) -> None:
    assert convert(convert(q, a, b), b, a) == pytest.approx(q, rel=1e-9)


@given(amounts, volume_units, volume_units)
def test_volume_conversion_round_trips(q: float, a: str, b: str) -> None:
    assert convert(convert(q, a, b), b, a) == pytest.approx(q, rel=1e-9)


@given(amounts, amounts, mass_units)
def test_conversion_is_monotonic(q1: float, q2: float, unit: str) -> None:
    lo, hi = sorted((q1, q2))
    assert convert(lo, unit, "g") <= convert(hi, unit, "g")


@given(amounts, amounts, volume_units)
def test_conversion_is_linear(q1: float, q2: float, unit: str) -> None:
    assert convert(q1 + q2, unit, "ml") == pytest.approx(
        convert(q1, unit, "ml") + convert(q2, unit, "ml"), rel=1e-9
    )


# --- quantities -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2", 2),
        ("1.5", 1.5),
        (".5", 0.5),
        ("1/2", 0.5),
        ("1 1/2", 1.5),
        ("½", 0.5),
        ("1½", 1.5),
        ("1 ½", 1.5),
        ("¾", 0.75),
        ("2-3", 2.5),
        ("2 - 3", 2.5),
        ("2 to 3", 2.5),
        ("1,5", 1.5),
    ],
)
def test_parse_quantity(text: str, expected: float) -> None:
    assert parse_quantity(text) == pytest.approx(expected)


@given(
    st.integers(min_value=0, max_value=50),
    st.sampled_from([Fraction(0), Fraction(1, 4), Fraction(1, 3), Fraction(1, 2), Fraction(3, 4)]),
)
def test_parse_quantity_round_trips_mixed_fractions(whole: int, frac: Fraction) -> None:
    if whole == 0 and frac == 0:
        return
    text = str(whole) if frac == 0 else f"{whole} {frac}" if whole else str(frac)
    assert parse_quantity(text) == pytest.approx(float(whole + frac))


# --- measures ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "quantity", "unit", "size"),
    [
        ("800g", 800, "g", None),
        ("150 g", 150, "g", None),
        ("1kg", 1, "kg", None),
        ("2 tablespoons", 2, "tbsp", None),
        ("1 tbs", 1, "tbsp", None),
        ("1/2 cup", 0.5, "cup", None),
        ("1½ cups", 1.5, "cup", None),
        ("250 ml", 250, "ml", None),
        ("12 oz", 12, "oz", None),
        ("2 lbs", 2, "lb", None),
        ("1 fl oz", 1, "fl_oz", None),
        ("1 clove", 1, "clove", None),
        ("2 cloves", 2, "clove", None),
        ("1", 1, None, None),
        ("3", 3, None, None),
        ("1 small finely diced", 1, None, "small"),
        ("2 large", 2, None, "large"),
        ("1 sliced", 1, None, None),
        ("1 tablespoon chopped", 1, "tbsp", None),
        ("200g/7oz", 200, "g", None),
        ("1 x 400g tin", 400, "g", None),
        ("2 x 400g tins", 800, "g", None),
        ("1 (400g) can", 400, "g", None),
        ("1 can", 1, "can", None),
        ("Juice of 1", 1, "juice", None),
        ("zest of 2", 2, "zest", None),
        ("1 tsp ", 1, "tsp", None),
        ("5 chopped cloves", 5, "clove", None),
        ("1 heaped tbsp", 1, "tbsp", None),
        ("grated zest of 2", 2, "zest", None),
        ("the juice and zest of one", 1, "juice", None),
        ("1 pot", 1, "pot", None),
        ("1 large chopped", 1, None, "large"),
    ],
)
def test_parse_measure(text: str, quantity: float, unit: str | None, size: str | None) -> None:
    m = parse_measure(text)
    assert m.quantity == pytest.approx(quantity)
    assert m.unit == unit
    assert m.size == size
    assert not m.vague


@pytest.mark.parametrize(
    ("text", "quantity", "unit"),
    [
        ("pinch", 1 / 16, "tsp"),
        ("a pinch", 1 / 16, "tsp"),
        ("2 pinches", 2 / 16, "tsp"),
        ("Dash", 1 / 8, "tsp"),
        ("splash", 1, "tbsp"),
        ("drizzle", 1, "tbsp"),
        ("To taste", 1 / 4, "tsp"),
        ("For frying", 1, "tbsp"),
        ("garnish", 1, "tsp"),
        ("Sprinkling", 1, "tsp"),
        ("knob", 15, "g"),
        ("handful", 30, "g"),
        ("2 handfuls", 60, "g"),
        ("to glaze", 1, "tsp"),
        ("for brushing", 1, "tsp"),
        ("topping", 1, "tsp"),
        ("", 1, None),
    ],
)
def test_parse_vague_measure(text: str, quantity: float, unit: str | None) -> None:
    m = parse_measure(text)
    assert m.quantity == pytest.approx(quantity)
    assert m.unit == unit
    assert m.vague


def test_measure_dimension() -> None:
    assert parse_measure("100g").dimension is Dimension.MASS
    assert parse_measure("1 cup").dimension is Dimension.VOLUME
    assert parse_measure("2 cloves").dimension is Dimension.COUNT
    assert parse_measure("3").dimension is Dimension.COUNT


@given(st.text(max_size=40))
def test_parse_measure_never_raises(text: str) -> None:
    m = parse_measure(text)
    assert isinstance(m, Measure)
    assert m.quantity >= 0
    assert math.isfinite(m.quantity)
    assert m.unit is None or m.unit in {*MASS_UNITS, *VOLUME_UNITS, *COUNT_UNITS}


@given(
    st.floats(min_value=0.25, max_value=500).map(lambda x: round(x, 2)),
    st.sampled_from(["g", "kg", "ml", "l", "tsp", "tbsp", "cup", "oz", "lb"]),
)
def test_parse_measure_round_trips_formatted_amounts(q: float, unit: str) -> None:
    m = parse_measure(f"{q:g} {unit}")
    assert m.quantity == pytest.approx(q)
    assert m.unit == unit
