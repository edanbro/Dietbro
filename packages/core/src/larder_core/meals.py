"""Meal slots and which recipes can fill them."""

import csv
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib import resources


class Slot(StrEnum):
    """A meal of the day, in eating order."""

    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


SLOT_ORDER: tuple[Slot, ...] = tuple(Slot)

# TheMealDB categories (plus our curated "Snack") -> the slots a recipe can fill. Sides are not a
# meal on their own; starters are light enough for lunch only.
_MAINS = frozenset({Slot.LUNCH, Slot.DINNER})
CATEGORY_SLOTS: dict[str, frozenset[Slot]] = {
    "Breakfast": frozenset({Slot.BREAKFAST}),
    "Beef": _MAINS,
    "Chicken": _MAINS,
    "Goat": _MAINS,
    "Lamb": _MAINS,
    "Miscellaneous": _MAINS,
    "Pasta": _MAINS,
    "Pork": _MAINS,
    "Seafood": _MAINS,
    "Vegan": _MAINS,
    "Vegetarian": _MAINS,
    "Starter": frozenset({Slot.LUNCH}),
    "Dessert": frozenset({Slot.SNACK}),
    "Snack": frozenset({Slot.SNACK}),
    "Side": frozenset(),
}


def meal_types(category: str | None) -> frozenset[Slot]:
    """Slots a recipe of this category can fill (empty: never planned on its own)."""
    return CATEGORY_SLOTS.get(category or "", frozenset())


# Data-quality limits for planning (docs/adr/0010-meal-slots-and-curated-recipes.md): a serving
# over this is almost always a parsing or matching error (deep-frying oil counted in full).
MAX_KCAL_PER_SERVING = 1000.0
MAX_OIL_SHARE = 0.25  # share of a recipe's grams that are "Fats and Oils"


@dataclass(frozen=True, slots=True)
class Override:
    source: str
    source_id: str
    slots: frozenset[Slot]  # empty = never planned
    note: str


@cache
def load_overrides() -> dict[tuple[str, str], Override]:
    """Reviewed reclassifications (data/recipe_overrides.csv): source, source_id, slots
    ('none' or pipe-separated slot names), note."""
    path = resources.files("larder_core") / "data" / "recipe_overrides.csv"
    with path.open(encoding="utf-8") as f:
        rows = [
            Override(
                r["source"],
                r["source_id"],
                frozenset()
                if r["slots"].strip() == "none"
                else frozenset(Slot(s.strip()) for s in r["slots"].split("|")),
                r["note"],
            )
            for r in csv.DictReader(f)
        ]
    return {(o.source, o.source_id): o for o in rows}


def recipe_slots(
    source: str,
    source_id: str,
    category: str | None,
    kcal_per_serving: float | None,
    oil_share: float,
) -> frozenset[Slot]:
    """Slots a recipe may fill: a reviewed override, else none when its nutrition looks broken,
    else by category."""
    override = load_overrides().get((source, source_id))
    if override is not None:
        return override.slots
    if kcal_per_serving is None or kcal_per_serving > MAX_KCAL_PER_SERVING:
        return frozenset()
    if oil_share > MAX_OIL_SHARE:
        return frozenset()
    return meal_types(category)
