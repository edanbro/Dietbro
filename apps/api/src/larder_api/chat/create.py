"""create_recipe: a drafted recipe -> a private, validated recipe row, or the problems to fix.

Steps: each ingredient's quantity is parsed (larder_core.units) and its name matched
(foods.match_food); an unmatched or unparseable ingredient is a problem (store-cupboard staples
like salt or water may be unquantified). Nutrition is computed from USDA data (never the
model's), allergens/diet from larder_core.tagging over names, instructions and matched foods.
Rejected if it conflicts with the user's allergens, diet or avoided foods, if it can't fill the
requested slot (larder_core.meals.recipe_slots: kcal per serving, oil share), or if it isn't
plannable (nutrition incomplete). Saved with source="generated", owner_user_id=user,
nutrition_complete=True; the planning catalog for this user includes it from then on.
"""

from dataclasses import dataclass

from larder_api.chat.scope import ChatScope
from larder_llm.schemas import CreateRecipeInput


@dataclass(frozen=True, slots=True)
class Created:
    recipe_id: int | None
    problems: list[str]  # empty when saved
    kcal_per_serving: int | None = None
    allergens: tuple[str, ...] = ()


async def create_recipe(scope: ChatScope, draft: CreateRecipeInput) -> Created:
    raise NotImplementedError
