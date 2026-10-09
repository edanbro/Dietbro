"""Allergen and animal-product tags for USDA foods and free-text ingredient names.

Safety rule: tagging is conservative. A false positive hides a recipe; a false negative can hurt
someone, so when in doubt, tag. Tags are derived at runtime from these rules (no stored column to
go stale); `data/food_tags.csv` overrides individual USDA foods.
"""

from dataclasses import dataclass
from enum import StrEnum

from larder_core.allergens import Allergen


class AnimalTag(StrEnum):
    MEAT = "meat"  # incl. poultry, game, offal, lard, suet, meat stock
    FISH = "fish"  # incl. anchovy in sauces, fish sauce
    SHELLFISH = "shellfish"  # crustaceans and molluscs
    DAIRY = "dairy"
    EGG = "egg"
    HONEY = "honey"
    GELATIN = "gelatin"  # and other slaughter by-products (rennet-free cheese is still dairy)


class Diet(StrEnum):
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    PESCATARIAN = "pescatarian"


FORBIDDEN: dict[Diet, frozenset[AnimalTag]] = {
    Diet.VEGAN: frozenset(AnimalTag),
    Diet.VEGETARIAN: frozenset(
        {AnimalTag.MEAT, AnimalTag.FISH, AnimalTag.SHELLFISH, AnimalTag.GELATIN}
    ),
    Diet.PESCATARIAN: frozenset({AnimalTag.MEAT, AnimalTag.GELATIN}),
}


def diet_allows(diet: Diet | None, animal: frozenset[AnimalTag]) -> bool:
    return diet is None or not (animal & FORBIDDEN[diet])


@dataclass(frozen=True, slots=True)
class FoodTags:
    allergens: frozenset[Allergen] = frozenset()
    animal: frozenset[AnimalTag] = frozenset()

    def __or__(self, other: "FoodTags") -> "FoodTags":
        return FoodTags(self.allergens | other.allergens, self.animal | other.animal)


def tag_food(fdc_id: int, description: str, category: str | None) -> FoodTags:
    """Tags for a USDA food: curated override, else category rules plus keyword rules."""
    raise NotImplementedError


def tag_text(text: str) -> FoodTags:
    """Tags implied by free text, e.g. a recipe line "soy sauce" or "worcestershire sauce"."""
    raise NotImplementedError
