"""Nutrition math. Food values are per 100 g; recipes sum ingredient grams."""

from collections.abc import Iterable
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


def estimate_servings(total_kcal: float, kcal_per_serving: float = TARGET_KCAL_PER_SERVING) -> int:
    """Serving count for a recipe without one: total energy / a typical portion, 1..12."""
    return max(1, min(MAX_ESTIMATED_SERVINGS, round(total_kcal / kcal_per_serving)))
