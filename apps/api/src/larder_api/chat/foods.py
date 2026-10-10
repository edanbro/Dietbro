"""Words -> USDA foods, for off-plan estimates and generated-recipe ingredients.

match_food(name): curated alias (larder_core.aliases) -> exact; else up to 8 trigram candidates
(pg_trgm on foods.description, restaurant and fast-food categories included) ranked by
larder_data-style token scoring; a clear winner is taken; otherwise, when online, the fast model
picks one of the candidates or none (structured output; its ModelCall goes to scope.calls) -
it can only choose among ids we gave it. Results are cached in ingredient_matches
(method alias | trigram | llm | unmatched).

grams_for(food, quantity): larder_core.units / quantities with the food's USDA portions
("2 slices", "300 g", "1 large"); no quantity -> one typical portion (the food's first portion,
else 100 g), flagged as estimated.
"""

from dataclasses import dataclass

from larder_api.chat.scope import ChatScope


@dataclass(frozen=True, slots=True)
class FoodMatch:
    food_id: int
    description: str
    method: str  # alias | trigram | llm


async def match_food(scope: ChatScope, name: str) -> FoodMatch | None:
    raise NotImplementedError


async def grams_for(scope: ChatScope, food_id: int, quantity: str | None) -> tuple[float, bool]:
    """(grams, estimated)."""
    raise NotImplementedError
