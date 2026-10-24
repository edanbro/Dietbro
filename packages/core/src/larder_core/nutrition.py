"""Nutrition math. Food values are per 100 g; recipes sum ingredient grams."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from typing import ClassVar, Self


@dataclass(frozen=True, slots=True)
class Nutrients:
    kcal: float = 0.0
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0
    fiber_g: float = 0.0
    sugars_g: float = 0.0
    sat_fat_g: float = 0.0
    sodium_mg: float = 0.0

    FIELDS: ClassVar[tuple[str, ...]] = (
        "kcal",
        "protein_g",
        "fat_g",
        "carbs_g",
        "fiber_g",
        "sugars_g",
        "sat_fat_g",
        "sodium_mg",
    )

    def scaled(self, factor: float) -> Self:
        return type(self)(*(getattr(self, f) * factor for f in self.FIELDS))

    def per_serving(self, servings: int) -> Self:
        if servings <= 0:
            raise ValueError(f"servings must be positive, got {servings}")
        return self.scaled(1 / servings)

    def __add__(self, other: Self) -> Self:
        return type(self)(*(getattr(self, f) + getattr(other, f) for f in self.FIELDS))


assert tuple(f.name for f in fields(Nutrients)) == Nutrients.FIELDS


# Vitamins and minerals, kept apart from Nutrients: there a missing value counts as 0, which
# is fine for energy and macros (foods without them are rare and small) but would understate
# these, which many foods have no value for.
MICROS: tuple[str, ...] = (
    "iron_mg",
    "calcium_mg",
    "potassium_mg",
    "vitamin_c_mg",
    "vitamin_d_ug",
    "folate_ug",
    "vitamin_b12_ug",
)
# An ingredient this heavy without a value makes the recipe's value unknown; lighter ones
# (spices, a squeeze of lemon) count as 0.
MICRO_MATTERS_G = 10.0


def micro_totals(
    lines: Iterable[tuple[Mapping[str, float | None], float]], servings: float
) -> dict[str, float | None]:
    """Per-serving vitamins and minerals from (per-100 g values, grams) lines; None for a
    nutrient when a line of MICRO_MATTERS_G or more has no value for it."""
    lines = list(lines)
    out: dict[str, float | None] = {}
    for name in MICROS:
        amount = 0.0
        for values, grams in lines:
            value = values.get(name)
            if value is None:
                if grams >= MICRO_MATTERS_G:
                    amount = None
                    break
                continue
            amount += value * grams / 100
        out[name] = None if amount is None or servings <= 0 else amount / servings
    return out


def for_grams(per_100g: Nutrients, grams: float) -> Nutrients:
    return per_100g.scaled(grams / 100)


def total(items: Iterable[tuple[Nutrients, float]]) -> Nutrients:
    """Sum of (per-100 g nutrients, grams) pairs."""
    acc = Nutrients()
    for per_100g, grams in items:
        acc = acc + for_grams(per_100g, grams)
    return acc


# A main-meal portion; used only when a recipe source gives no serving count.
TARGET_KCAL_PER_SERVING = 650
MAX_ESTIMATED_SERVINGS = 12
# A big bowlful: a pot of soup is several servings even when its energy says one.
MAX_GRAMS_PER_SERVING = 500


def estimate_servings(
    total_kcal: float, kcal_per_serving: float = TARGET_KCAL_PER_SERVING, total_grams: float = 0
) -> int:
    """Serving count for a recipe without one: total energy / a typical portion, or more when
    that would make a serving heavier than MAX_GRAMS_PER_SERVING; 1..12."""
    by_energy = round(total_kcal / kcal_per_serving)
    by_weight = round(total_grams / MAX_GRAMS_PER_SERVING)
    return max(1, min(MAX_ESTIMATED_SERVINGS, max(by_energy, by_weight)))
