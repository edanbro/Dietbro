"""Meal slots and which recipes can fill them."""

import csv
from collections.abc import Mapping
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

# TheMealDB categories (plus our curated "Snack" and "Light meal") -> the slots a recipe can fill.
# Sides are not a meal on their own; starters are light enough for lunch only.
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
    "Light meal": frozenset({Slot.LUNCH}),
    "Dessert": frozenset({Slot.SNACK}),
    "Snack": frozenset({Slot.SNACK}),
    "Side": frozenset(),
}


def meal_types(category: str | None) -> frozenset[Slot]:
    """Slots a recipe of this category can fill (empty: never planned on its own)."""
    return CATEGORY_SLOTS.get(category or "", frozenset())


# A main meal's usual share of the day (preferences.meal_modes): what's kept free for a meal
# the user sorts out themselves, among the meals they eat. A planned meal may carry at most
# MAX_MEAL_SHARE of the day on average (portion limits make more impractical).
MEAL_SHARE: dict[Slot, float] = {Slot.BREAKFAST: 0.25, Slot.LUNCH: 0.35, Slot.DINNER: 0.40}
MAX_MEAL_SHARE = 0.55


def meals_problem(modes: Mapping[Slot, str]) -> str | None:
    """Why these modes can't be planned, or None: at least one main meal is planned, and the
    planned ones aren't left more than MAX_MEAL_SHARE of the day each."""
    planned = [s for s in MEAL_SHARE if modes[s] == "plan"]
    if not planned:
        return "Plan at least one of breakfast, lunch and dinner."
    eaten = sum(MEAL_SHARE[s] for s in MEAL_SHARE if modes[s] != "skip")
    if sum(MEAL_SHARE[s] for s in planned) / eaten / len(planned) > MAX_MEAL_SHARE:
        return (
            "With those meals skipped, each planned meal would be over half your day. Plan "
            "another meal, or say you sort one out yourself instead of skipping it."
        )
    return None


def day_shares(modes: Mapping[Slot, str]) -> dict[Slot, float]:
    """Each planned main meal as a fraction of the day they eat."""
    eaten = sum(MEAL_SHARE[s] for s in MEAL_SHARE if modes[s] != "skip")
    return {s: MEAL_SHARE[s] / eaten for s in MEAL_SHARE if modes[s] == "plan"}


def own_shares(modes: Mapping[Slot, str]) -> dict[Slot, float]:
    """Each meal the user sorts out themselves, as a fraction of the day they eat."""
    eaten = sum(MEAL_SHARE[s] for s in MEAL_SHARE if modes[s] != "skip")
    return {s: MEAL_SHARE[s] / eaten for s in MEAL_SHARE if modes[s] == "own"}


# Data-quality limits for planning (docs/adr/0010-meal-slots-and-curated-recipes.md): a serving
# over this is almost always a parsing or matching error (deep-frying oil counted in full).
MAX_KCAL_PER_SERVING = 1000.0
MAX_OIL_SHARE = 0.25  # share of a recipe's grams that are "Fats and Oils"
# 6 g of salt, an adult's whole day: a whole pot's seasoning counted in one serving.
MAX_SODIUM_MG_PER_SERVING = 2400.0
# What a serving must have to stand as a meal (docs/adr/0019-everyday-meals.md): below this a
# catalogue recipe is a side or a starter, whatever its category says. Half this for breakfast
# would still pass a banana; a snack over the limit is a slice of a big bake, not a snack.
MIN_MEAL_KCAL = 250.0
MIN_MEAL_PROTEIN_G = 10.0
MIN_BREAKFAST_KCAL = 200.0
MAX_SNACK_KCAL = 350.0
CATALOGUE_SOURCES = frozenset({"mealdb", "curated"})


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
    sodium_mg_per_serving: float | None = None,
    protein_g_per_serving: float | None = None,
) -> frozenset[Slot]:
    """Slots a recipe may fill: a reviewed override, else none when its nutrition looks broken,
    else by category, less the slots a catalogue recipe is too small or too big for. A user's own
    recipes keep their category's slots: they know what they eat."""
    override = load_overrides().get((source, source_id))
    if override is not None:
        return override.slots
    if kcal_per_serving is None or kcal_per_serving > MAX_KCAL_PER_SERVING:
        return frozenset()
    if oil_share > MAX_OIL_SHARE:
        return frozenset()
    if (sodium_mg_per_serving or 0) > MAX_SODIUM_MG_PER_SERVING:
        return frozenset()
    slots = meal_types(category)
    if source not in CATALOGUE_SOURCES:
        return slots
    too_little_protein = (
        protein_g_per_serving is not None and protein_g_per_serving < MIN_MEAL_PROTEIN_G
    )
    if kcal_per_serving < MIN_MEAL_KCAL or too_little_protein:
        slots -= _MAINS
    if kcal_per_serving < MIN_BREAKFAST_KCAL:
        slots -= {Slot.BREAKFAST}
    if kcal_per_serving > MAX_SNACK_KCAL:
        slots -= {Slot.SNACK}
    return slots


@cache
def load_everyday() -> dict[tuple[str, str], frozenset[Slot]]:
    """Reviewed everyday meals (data/everyday_recipes.csv): source, source_id, slots ('none' or
    pipe-separated slot names), note."""
    path = resources.files("larder_core") / "data" / "everyday_recipes.csv"
    with path.open(encoding="utf-8") as f:
        return {
            (r["source"], r["source_id"]): frozenset()
            if r["slots"].strip() == "none"
            else frozenset(Slot(s.strip()) for s in r["slots"].split("|"))
            for r in csv.DictReader(f)
        }


def everyday_slots(source: str, source_id: str, slots: frozenset[Slot]) -> frozenset[Slot]:
    """The slots in which this recipe is a normal, familiar meal: those the reviewed list gives
    it, else a curated recipe's own slots, with a full main counted as a dinner (a roast fills a
    lunch only for someone who chose it). Only ever a subset of `slots`."""
    listed = load_everyday().get((source, source_id))
    if listed is not None:
        return listed & slots
    if source != "curated":
        return frozenset()
    return slots - {Slot.LUNCH} if slots >= _MAINS else slots
