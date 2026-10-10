"""create_recipe: a drafted recipe -> a private, validated recipe row, or the problems to fix.

1. Each ingredient: quantity parsed (larder_core.units, grams via the food's portions) and name
   matched (foods.match_food). Unmatched or unparseable -> a problem ("couldn't match 'X' - use a
   common ingredient name"); store-cupboard staples (salt, pepper, water, dried herbs) may be
   unquantified.
2. Build the row (source="generated", owner_user_id=user, servings, category from the slot)
   and run the same path the planner uses: planning.recipe_facts -> solver Recipe + foods. The
   gate is exactly the planner's: `candidates.allowed(recipe, foods, profile)` and `slot in
   facts.slots` (kcal per serving, oil share). For a restricted user any line that isn't an
   exact curated match counts as unresolved, so `allowed` rejects it - report "couldn't verify
   'X' against your allergies; use a common ingredient name". Never add a separate notion of a
   trusted match.
3. Also reject when the name or instructions mention, as a whole word, an avoided food's name
   or alias, or an allergen word for the user's allergens (the tagger's text rules).
4. Nutrition from USDA data only. Save (nutrition_complete=True), commit before returning so a
   request_replan in the same turn (its own session) can use the id.
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
