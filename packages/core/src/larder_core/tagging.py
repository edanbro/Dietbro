"""Allergen and animal-product tags for USDA foods, ingredient text and whole recipes.

Safety rule: tagging is conservative. A false positive hides a recipe; a false negative can hurt
someone, so when in doubt, tag. Tags are derived at runtime from these rules plus reviewed data
files (no stored column to go stale):

- `data/food_tags.csv`: per-USDA-food additions (and rare, noted removals) on top of the rules.
- `data/line_tags.csv`: reviewed ingredient names whose matched food is an approximation or an
  automatic (embedding) match: the extra tags the real ingredient carries ('-' = reviewed, none).

Text matching (`tag_text`) normalises (NFKD, strip accents, casefold, non-alphanumerics -> space)
and matches whole tokens or phrases, with plural/inflection variants and a short list of compound
suffixes (saltfish, buttermilk, shortbread), never raw substrings ("coat" is not oats).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from larder_core.allergens import Allergen


class AnimalTag(StrEnum):
    MEAT = "meat"  # incl. poultry, game, offal, lard, suet, meat stock, frog
    FISH = "fish"  # incl. anchovy in sauces, fish sauce
    SHELLFISH = "shellfish"  # crustaceans and molluscs
    DAIRY = "dairy"
    EGG = "egg"
    HONEY = "honey"
    GELATIN = "gelatin"  # gelatine, isinglass and other slaughter by-products
    RENNET = "rennet"  # traditional hard cheeses made with animal rennet (parmesan, pecorino…)


class Diet(StrEnum):
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    PESCATARIAN = "pescatarian"


FORBIDDEN: dict[Diet, frozenset[AnimalTag]] = {
    Diet.VEGAN: frozenset(AnimalTag),
    Diet.VEGETARIAN: frozenset(
        {AnimalTag.MEAT, AnimalTag.FISH, AnimalTag.SHELLFISH, AnimalTag.GELATIN, AnimalTag.RENNET}
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

    def normalised(self) -> "FoodTags":
        """Couple allergens and animal tags so neither side can be forgotten: milk <-> dairy,
        eggs <-> egg, fish <-> fish, crustaceans/molluscs -> shellfish, and shellfish with
        neither allergen -> both. Every function here returns normalised tags."""
        a, t = set(self.allergens), set(self.animal)
        if Allergen.MILK in a or AnimalTag.DAIRY in t:
            a.add(Allergen.MILK)
            t.add(AnimalTag.DAIRY)
        if Allergen.EGGS in a or AnimalTag.EGG in t:
            a.add(Allergen.EGGS)
            t.add(AnimalTag.EGG)
        if Allergen.FISH in a or AnimalTag.FISH in t:
            a.add(Allergen.FISH)
            t.add(AnimalTag.FISH)
        if Allergen.CRUSTACEANS in a or Allergen.MOLLUSCS in a:
            t.add(AnimalTag.SHELLFISH)
        elif AnimalTag.SHELLFISH in t:
            a |= {Allergen.CRUSTACEANS, Allergen.MOLLUSCS}
        return FoodTags(frozenset(a), frozenset(t))


@dataclass(frozen=True, slots=True)
class Line:
    """One recipe ingredient line, as far as tagging is concerned."""

    raw_name: str
    food: FoodTags | None  # tags of the matched food; None = no food matched
    # True when the match is exact (a non-approximation curated alias). Approximate and
    # automatic matches only count as known once their name is reviewed in line_tags.csv.
    exact: bool


@dataclass(frozen=True, slots=True)
class RecipeTags:
    allergens: frozenset[Allergen]
    animal: frozenset[AnimalTag]
    unresolved: int  # lines whose allergen content isn't established

    @property
    def complete(self) -> bool:
        return self.unresolved == 0

    def suitable_for(self) -> list[Diet]:
        return [d for d in Diet if self.complete and diet_allows(d, self.animal)]


def tag_food(fdc_id: int, description: str, category: str | None) -> FoodTags:
    """Tags for a USDA food: category rules | keyword rules on the description | food_tags.csv
    additions, minus noted removals."""
    raise NotImplementedError


def tag_text(text: str) -> FoodTags:
    """Tags implied by free text: an ingredient line ("soy sauce", "worcestershire sauce"), a
    recipe name ("Egg Drop Soup") or instructions ("add 1 egg"). Utensil phrases ("fish slice",
    "butter knife") and "<x>-sized" don't count."""
    raise NotImplementedError


def recipe_tags(
    name: str, category: str | None, instructions: str, lines: Iterable[Line]
) -> RecipeTags:
    """The single definition of a recipe's tags, used by the planner catalog and the recipe page:
    union of matched foods' tags, `tag_text` of every raw name, the name and the instructions,
    reviewed line tags, and category backstops (Beef/Chicken/Pork/Lamb/Goat -> meat; Seafood ->
    fish + shellfish, plus all three allergens when no ingredient carries one)."""
    raise NotImplementedError
