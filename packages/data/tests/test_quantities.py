import pytest
from hypothesis import given
from hypothesis import strategies as st

from larder_core.units import parse_measure
from larder_data.quantities import Portion, density, grams_for

ONION = [
    Portion(1, "cup", "chopped", 160),
    Portion(1, "cup", "sliced", 115),
    Portion(1, "tbsp", "chopped", 10),
    Portion(1, "large", None, 150),
    Portion(1, "medium", '(2-1/2" dia)', 110),
    Portion(1, "small", None, 70),
]
GARLIC = [Portion(1, "tsp", None, 2.8), Portion(1, "clove", None, 3), Portion(1, "cup", None, 136)]
POTATO = [
    Portion(1, "potato", 'small (1-3/4" to 2-1/2" dia)', 170),
    Portion(1, "potato", 'medium (2-1/4" to 3-1/4" dia)', 213),
    Portion(1, "potato", 'large (3" to 4-1/4" dia)', 369),
    Portion(0.5, "cup", "diced", 75),
]
OIL = [Portion(1, "tbsp", None, 13.5), Portion(1, "cup", None, 216)]
EGG = [Portion(1, "small", None, 38), Portion(1, "large", None, 50), Portion(1, "medium", None, 44)]


def grams(measure: str, portions: list[Portion], name: str = "x") -> float | None:
    return grams_for(parse_measure(measure), portions, name)


def test_mass_is_direct() -> None:
    assert grams("800g", []) == 800
    assert grams("1 lb", []) == pytest.approx(453.6, abs=0.1)


def test_volume_uses_the_foods_density() -> None:
    assert grams("2 tbsp", OIL) == pytest.approx(27)
    assert grams("1 cup", OIL) == pytest.approx(216)
    # median of chopped/sliced/tbsp densities
    assert grams("1 cup", ONION) == pytest.approx(160, rel=0.05)


def test_volume_without_density_falls_back_to_category() -> None:
    no_volume = [Portion(1, "large", None, 150)]
    assert grams("1 cup", no_volume) == pytest.approx(240)
    assert grams_for(parse_measure("1 tbsp"), [], "oil", "Fats and Oils") == pytest.approx(13.8)


def test_piece_weights_for_foods_weighed_by_volume() -> None:
    spice = [Portion(1, "tsp", None, 0.6), Portion(1, "tbsp", None, 1.8)]
    assert grams("2", spice, "bay leaf") == pytest.approx(0.4)
    assert grams("1", spice, "cinnamon stick") == 3
    assert grams("1", spice, "unknown thing") is None


def test_empty_measure_is_a_tablespoon() -> None:
    assert grams("", OIL) == pytest.approx(13.5)


def test_count_unit_matches_portion() -> None:
    assert grams("2 cloves", GARLIC) == pytest.approx(6)


def test_size_word() -> None:
    assert grams("1 large", ONION) == 150
    assert grams("2 small", ONION) == 140
    assert grams("1 large", POTATO) == 369


def test_plain_count_prefers_medium() -> None:
    assert grams("1", ONION) == 110
    assert grams("3", POTATO) == pytest.approx(639)
    assert grams("2", EGG) == 88


def test_plain_count_for_garlic_is_a_clove() -> None:
    assert grams("3", GARLIC, "garlic") == pytest.approx(9)


def test_juice_and_zest_use_fruit_defaults() -> None:
    assert grams("Juice of 1", [], "lemon") == 30
    assert grams("juice of 2", [], "lime") == 40
    assert grams("zest of 1", [], "orange") == 3


def test_count_defaults_when_no_portion() -> None:
    assert grams("1 can", [], "chopped tomatoes") == 400
    assert grams("1 tin", [], "x") == 400
    assert grams("2 sprigs", [], "thyme") == 2


def test_vague_measures_are_small() -> None:
    assert grams("pinch", GARLIC) == pytest.approx(5 / 16 * 2.8 / 5 * 1, rel=0.2)
    knob = grams("knob", [])
    assert knob == 15


def test_density_ignores_mass_and_count_portions() -> None:
    assert density(OIL) == pytest.approx(0.9)
    assert density([Portion(1, "large", None, 50)]) is None


@given(st.floats(min_value=0.1, max_value=50), st.sampled_from(["tsp", "tbsp", "cup", "ml"]))
def test_volume_grams_scale_linearly(q: float, unit: str) -> None:
    one = grams_for(parse_measure(f"1 {unit}"), OIL, "oil")
    many = grams_for(parse_measure(f"{q} {unit}"), OIL, "oil")
    assert one is not None
    assert many is not None
    assert many == pytest.approx(q * one, rel=1e-6)
