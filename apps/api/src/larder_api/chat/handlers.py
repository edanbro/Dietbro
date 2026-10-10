"""Tool handlers bound to one ChatScope (larder_llm.tools.TOOLS -> functions). Each returns
compact JSON for the model (ToolOutcome.content), never raises for user-level problems
(is_error=True with a short reason instead), and touches only `scope.user_id`'s data: every
plan is loaded with `MealPlan.user_id == scope.user_id`, every recipe through `visible_recipe`.

get_plan, get_pantry, explain_meal, explain_plan_diff (reads the stored outcome in PlanStats
v2; the parent is also the user's): read-only views of today onward.
search_recipes: search.search_recipes.
request_replan: replan.apply_changes(source="chat"); appends to scope.outcomes and emits an
`outcome` event.
create_recipe: create.create_recipe; appends to scope.created_recipes and emits `recipe`.
Unknown or invisible ids get the same answer as a missing one ("I can't use that recipe").
"""

from larder_api.chat.scope import ChatScope
from larder_core.meals import Slot
from larder_db import models as db
from larder_llm.agent import Handler


async def visible_recipe(scope: ChatScope, recipe_id: int) -> db.Recipe | None:
    """The recipe if it is in the shared catalogue or owned by this user, else None."""
    raise NotImplementedError


async def guard_recipe(scope: ChatScope, recipe_id: int, slot: Slot) -> str | None:
    """None if the recipe may be chosen for `slot` for this user: visible, plannable
    (nutrition complete, servings), `slot` among its meal types (recipe_facts), and
    `candidates.allowed` under the user's current profile. Else the user-facing reason."""
    raise NotImplementedError


def make_handlers(scope: ChatScope) -> dict[str, Handler]:
    raise NotImplementedError
