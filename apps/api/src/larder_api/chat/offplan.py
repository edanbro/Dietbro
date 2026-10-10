"""Estimate what an off-plan meal contained: items (or the description as one item) -> foods
(foods.match_food) -> grams (foods.grams_for) -> macros computed from USDA per-100 g values.
The model's own numbers are never used. Unmatched items are reported, not guessed; if nothing
matches, the estimate falls back to the planned meal at that slot (or 600 kcal for a main, 250
for a snack) and says so."""

from dataclasses import dataclass

from larder_api.chat.scope import ChatScope
from larder_llm.schemas import AteOffPlan
from larder_solver import Macros


@dataclass(frozen=True, slots=True)
class Estimate:
    macros: Macros
    items: list[dict[str, object]]  # {"name", "food_id", "food", "grams"} per matched item
    unmatched: list[str]
    note: str | None  # "Estimated as a typical dinner - tell me what was in it to be precise."


async def estimate(scope: ChatScope, change: AteOffPlan) -> Estimate:
    raise NotImplementedError
