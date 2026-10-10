"""Tool handlers bound to one ChatScope (larder_llm.tools.TOOLS -> functions). Each returns
compact JSON for the model (ToolOutcome.content), never raises for user-level problems
(is_error=True with a short reason instead), and touches only `scope.user`'s data.

get_plan, get_pantry, explain_meal, explain_plan_diff: read-only views.
search_recipes: search.search_recipes.
request_replan: replan.apply_changes(source="chat"); appends to scope.outcomes.
create_recipe: create.create_recipe; appends to scope.created_recipes.
"""

from larder_api.chat.scope import ChatScope
from larder_llm.agent import Handler


def make_handlers(scope: ChatScope) -> dict[str, Handler]:
    raise NotImplementedError
