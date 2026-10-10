"""Words -> USDA foods, for off-plan estimates and generated-recipe ingredients.

match_food(name): curated alias (larder_core.aliases) -> exact; else up to 8 trigram candidates
(pg_trgm on foods.description, restaurant and fast-food categories included) ranked by token
overlap; a clear winner is taken; otherwise, when scope.models.fast is set, the fast model picks
one of the candidate ids or none (structured output; it can only choose among ids we gave it).
Nothing is cached: chat traffic must not leak into ingredient_matches, which the importer's
resolver reuses for the shared catalogue (and which has no user to export or delete).

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
