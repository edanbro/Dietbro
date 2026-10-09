"""Meal slots and which recipes can fill them."""

from enum import StrEnum


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
