"""A nutrition grade A-E per 100 g, computed with the Nutri-Score method for general foods
(2023 update): "unfavourable" points for energy, sugars, saturated fat and salt, minus
"favourable" points for protein, fibre and the share of fruit, vegetables and legumes.

This is our estimate from the nutrients we have, not an official Nutri-Score (shown as
"Nutrition grade (Nutri-Score method)", without the logo). Beverages, fats and oils, and cheese
follow other Nutri-Score rules, so they get no grade here; a product's own grade from Open Food
Facts is preferred when it has one.
"""

from bisect import bisect_left
from dataclasses import dataclass

__all__ = ["Grade", "NutriInput", "grade", "score"]

type Grade = str  # "A".."E"

# Thresholds: points = how many thresholds the value is strictly above.
_ENERGY_KJ = (335, 670, 1005, 1340, 1675, 2010, 2345, 2680, 3015, 3350)  # 0-10
_SUGARS_G = (3.4, 6.8, 10, 14, 17, 20, 24, 27, 31, 34, 37, 41, 44, 48, 51)  # 0-15
_SAT_FAT_G = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)  # 0-10
_SALT_G = tuple(round(0.2 * i, 1) for i in range(1, 21))  # 0.2 .. 4.0: 0-20
_PROTEIN_G = (2.4, 4.8, 7.2, 9.6, 12, 14, 17)  # 0-7
_FIBRE_G = (3.0, 4.1, 5.2, 6.3, 7.4)  # 0-5

UNGRADED_CATEGORIES = frozenset({"Beverages", "Fats and Oils"})
_CHEESE_WORDS = ("cheese",)


@dataclass(frozen=True, slots=True)
class NutriInput:
    """Per 100 g. None: unknown (counted as 0 for favourable, and blocks the grade for the
    unfavourable ones, which can't be assumed)."""

    kcal: float | None
    sugars_g: float | None
    sat_fat_g: float | None
    sodium_mg: float | None
    protein_g: float | None
    fiber_g: float | None
    fruit_veg_pct: float = 0.0  # fruit, vegetables and legumes, % of the weight


def _points(value: float, thresholds: tuple[float, ...]) -> int:
    """How many thresholds `value` is strictly above."""
    return bisect_left(thresholds, value) if value > thresholds[0] else 0


def _fruit_veg_points(pct: float) -> int:
    return 5 if pct > 80 else 2 if pct > 60 else 1 if pct > 40 else 0


def score(n: NutriInput) -> int | None:
    """The Nutri-Score points (lower is better); None when a nutrient that counts against
    the food is unknown."""
    if n.kcal is None or n.sugars_g is None or n.sat_fat_g is None or n.sodium_mg is None:
        return None
    salt_g = n.sodium_mg * 2.5 / 1000
    bad = (
        _points(n.kcal * 4.184, _ENERGY_KJ)
        + _points(n.sugars_g, _SUGARS_G)
        + _points(n.sat_fat_g, _SAT_FAT_G)
        + _points(salt_g, _SALT_G)
    )
    fruit_veg = _fruit_veg_points(n.fruit_veg_pct)
    fibre = _points(n.fiber_g or 0, _FIBRE_G)
    protein = _points(n.protein_g or 0, _PROTEIN_G)
    # Protein doesn't count for foods high in unfavourable points, unless mostly fruit/veg.
    if bad >= 11 and fruit_veg < 5:
        protein = 0
    return bad - protein - fibre - fruit_veg


def grade(n: NutriInput, *, category: str | None = None, description: str = "") -> Grade | None:
    """A-E, or None when it can't be graded this way (drinks, fats, cheese, unknown values)."""
    if category in UNGRADED_CATEGORIES:
        return None
    if any(w in description.lower() for w in _CHEESE_WORDS):
        return None
    s = score(n)
    if s is None:
        return None
    if s <= 0:
        return "A"
    if s <= 2:
        return "B"
    if s <= 10:
        return "C"
    if s <= 18:
        return "D"
    return "E"
