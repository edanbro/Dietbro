import pytest

from larder_core.nutrigrade import NutriInput, grade, score


def food(**values: float | None) -> NutriInput:
    base: dict[str, float | None] = {
        "kcal": 0,
        "sugars_g": 0,
        "sat_fat_g": 0,
        "sodium_mg": 0,
        "protein_g": 0,
        "fiber_g": 0,
    }
    return NutriInput(**(base | values))  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        # Apples: 52 kcal (218 kJ, 0), sugars 10.4 g (3), fibre 2.4 g (0), fruit 100% (5) -> -2
        (food(kcal=52, sugars_g=10.4, fiber_g=2.4, fruit_veg_pct=100), "A"),
        # Porridge oats: 379 kcal (1586 kJ, 4), sugars 1 (0), sat fat 1.2 (1), protein 13 (5),
        # fibre 10 (5) -> 5 - 10 = -5
        (food(kcal=379, sugars_g=1, sat_fat_g=1.2, protein_g=13, fiber_g=10), "A"),
        # Milk chocolate: 535 kcal (2238 kJ, 6), sugars 52 (15), sat fat 18.5 (10), salt 0.2
        # (0): bad 31, protein ignored, fibre 3.4 (1) -> 30
        (
            food(kcal=535, sugars_g=52, sat_fat_g=18.5, sodium_mg=79, protein_g=7.7, fiber_g=3.4),
            "E",
        ),
        # Back bacon: 215 kcal (900 kJ, 2), sat fat 6 (5), salt 3.5 g (17): bad 24 -> 24
        (food(kcal=215, sat_fat_g=6, sodium_mg=1410, protein_g=16.5), "E"),
    ],
)
def test_known_foods(n: NutriInput, expected: str) -> None:
    assert grade(n) == expected


def test_thresholds_are_strictly_above() -> None:
    assert score(food(kcal=335 / 4.184)) == 0  # exactly 335 kJ: no point
    assert score(food(kcal=336 / 4.184)) == 1


def test_protein_counts_only_when_unfavourable_points_are_low() -> None:
    # 837 kJ (2) + sat fat 1.5 (1) + salt 1.0 g (4) = 7: protein 20 g (7) counts.
    lean = food(kcal=200, sat_fat_g=1.5, sodium_mg=400, protein_g=20)
    # 1255 kJ (3) + sat fat 8 (7) + salt 2.0 g (9) = 19 >= 11: protein doesn't count.
    fatty = food(kcal=300, sat_fat_g=8, sodium_mg=800, protein_g=20)
    assert score(lean) == 7 - 7
    assert score(fatty) == 19


def test_unknown_unfavourable_nutrients_mean_no_grade() -> None:
    assert grade(food(sodium_mg=None)) is None
    assert grade(food(fiber_g=None)) == "A"  # unknown favourable ones just don't help


@pytest.mark.parametrize(
    ("category", "description"),
    [
        ("Beverages", "Cola"),
        ("Fats and Oils", "Olive oil"),
        ("Dairy and Egg Products", "Cheese, cheddar"),
    ],
)
def test_other_nutri_score_families_are_not_graded(category: str, description: str) -> None:
    assert grade(food(kcal=100), category=category, description=description) is None
