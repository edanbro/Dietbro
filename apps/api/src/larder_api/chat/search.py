"""search_recipes: recipes safe for this user that match a query, for cravings and swaps.

Pool: the plannable catalog plus the user's private recipes, filtered by the planner's hard
filters (larder_solver.candidates.allowed: allergens incl. text-derived, diet, avoided foods,
unverifiable ingredients for restricted users) and, if given, slot eligibility. No embeddings in
the API (ADR-0013): the model supplies words; we score them against recipe name, category,
cuisine, MealDB tags and ingredient names (whole-word, a small synonym table for qualities like
'spicy' -> chilli, curry, jalapeno, harissa...), then preference and pantry overlap, then id.
"""

from dataclasses import dataclass

from larder_api.chat.scope import ChatScope
from larder_core.meals import Slot


@dataclass(frozen=True, slots=True)
class RecipeHit:
    id: int
    name: str
    cuisine: str | None
    slots: tuple[Slot, ...]
    kcal_per_serving: int
    protein_g_per_serving: int
    matched: tuple[str, ...]  # which query words matched, for the model to explain
    uses_pantry: tuple[str, ...]  # pantry foods it uses


async def search_recipes(
    scope: ChatScope, query: str, slot: Slot | None, limit: int = 5
) -> list[RecipeHit]:
    raise NotImplementedError
