"""The executor: typed changes -> a new plan version. The only way the chat changes a plan.

Target plan: the user's latest plan if `scope.today` falls inside it; otherwise a fresh plan
from `scope.today` (as POST /plans would make), with the changes applied to it. No plan and no
setup -> every change fails with a "make a plan first" / setup message.

Building the replan problem (planning.make_problem plus):
- `previous` = the current plan (churn penalty keeps unrelated meals; Weights.churn).
- Locks: every meal on days before today is locked as it is. On today, meals in slots before the
  earliest slot a change touches today are locked too (assumed eaten).
- The current plan's recipes are forced into their slots' candidate lists (so "keep" is always
  possible); locked recipes are added to `problem.recipes`.
- The user's private (generated) recipes join the catalog for this user only.
Per change (in order; a failed change doesn't stop the others):
- Craving: candidate recipes = `recipe_id` if given (must be visible to the user and pass the
  hard filters, else fail), else search(dish + tags, slot) top 5. Try each as a lock at
  (date, slot) in rank order; keep the first whose plan passes the outcome rules. None fits:
  hard -> failure "No safe ... fits ..."; soft -> failure note, plan unchanged for this change.
  Slot missing: dinner if the date is today and no slot given, else the slot the plan has
  that best matches (lunch/dinner) - or fail asking which meal.
- AteOffPlan: estimate (offplan.estimate) -> MealLog(kind=off_plan); `extra[day] += macros`;
  if a slot is given, that slot is locked to None (no planned meal). Past days: log only.
- Skip: lock (day, slot) to None; MealLog(kind=skipped); if eating_elsewhere, the planned meal's
  macros count as eaten (`extra`), so the rest of the day is unchanged.
- Swap: lock (day, slot) to a different recipe: `recipe_id`, or search(dish/tags) like a
  craving, or (nothing given) the planner's best alternative with the current recipe excluded
  from that slot's candidates (other days keeping it are locked to it).
Then: run the planner once with all locks/extra -> planning.check_outcome (validator; safety and
structural violations are never saved) -> save as version+1 with parent_id, locked meals marked
`locked=True` -> ReplanOutcome with the slot-by-slot diff (larder_llm.outcome.SlotChange; reason
= the change that caused it, else "rebalance") and new kcal of changed days. One `cravings` row
per change (status applied|failed|unchanged), MealLog rows linked to the new plan.
"""

from collections.abc import Sequence
from typing import Literal

from larder_api.chat.scope import ChatScope
from larder_llm.outcome import ReplanOutcome
from larder_llm.schemas import Change


async def apply_changes(
    scope: ChatScope, changes: Sequence[Change], *, source: Literal["chat", "offline"]
) -> ReplanOutcome:
    raise NotImplementedError
