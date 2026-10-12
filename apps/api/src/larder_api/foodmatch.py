"""Words -> USDA foods without a model: the offline half of the matcher, shared by the chat
(off-plan estimates, drafted recipes; larder_api.chat.foods adds the model tiebreak) and
receipt intake (larder_api.receipts).

alias_food(name): the curated alias table (larder_core.aliases) on the normalised name.
trigram_food(name): up to 8 trigram candidates (pg_trgm on foods.description) ranked by token
overlap; the top one is taken only when it is a clear winner (every word of the name and fewer
other words than any rival that also has them all). Nothing is cached here: user text must not
leak into ingredient_matches, which the importer's resolver reuses for the shared catalogue.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from larder_core.aliases import load_aliases
from larder_core.names import normalise_name, singular
from larder_db import models as db

MAX_CANDIDATES = 8
# Not things you'd keep in a pantry (type-ahead search and receipts leave them out).
NOT_GROCERIES = (
    "Baby Foods",
    "Fast Foods",
    "Restaurant Foods",
    "Meals, Entrees, and Side Dishes",
    "American Indian/Alaska Native Foods",
)

_CANDIDATES_SQL = text(
    """
    SELECT id, description
    FROM foods
    WHERE kcal IS NOT NULL
      AND NOT (coalesce(category, '') = ANY(:excluded))
      AND (description ILIKE '%' || :q || '%' OR :q <% description)
    ORDER BY word_similarity(:q, description) DESC, (data_type = 'sr_legacy') DESC,
             length(description), id
    LIMIT :limit
    """
)
_TOKEN = re.compile(r"[a-z0-9]+")
_FILLER = frozenset({"a", "an", "the", "of", "with", "and", "some", "my", "fresh", "homemade"})


@dataclass(frozen=True, slots=True)
class FoodMatch:
    food_id: int
    description: str
    method: str  # alias | trigram | llm (chat) ; receipt | partial | user (receipts)


@dataclass(frozen=True, slots=True)
class Candidate:
    food_id: int
    description: str
    coverage: float  # share of the name's words found in the description
    extra: int  # description words beyond the name's


def tokens(value: str) -> frozenset[str]:
    """Lowercase words without accents, singular, minus filler words."""
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return frozenset(singular(t) for t in _TOKEN.findall(folded)) - _FILLER


def rank(name: str, rows: Sequence[tuple[int, str]]) -> list[Candidate]:
    wanted = tokens(name)
    out: list[Candidate] = []
    for food_id, description in rows:
        have = tokens(description)
        coverage = len(wanted & have) / len(wanted) if wanted else 0.0
        out.append(Candidate(food_id, description, coverage, len(have - wanted)))
    # Stable: equal candidates keep the SQL order (similarity, SR legacy, shorter).
    return sorted(out, key=lambda c: (-c.coverage, c.extra))


def clear_winner(ranked: Sequence[Candidate]) -> Candidate | None:
    """The top candidate when it has every word of the name and strictly fewer other words
    than any other candidate that has them all."""
    if not ranked or ranked[0].coverage < 1:
        return None
    top = ranked[0]
    rival = next((c for c in ranked[1:] if c.coverage >= 1), None)
    return top if rival is None or rival.extra > top.extra else None


async def alias_food(session: AsyncSession, name: str) -> FoodMatch | None:
    fdc_id = load_aliases().get(normalise_name(name))
    if fdc_id is None or (food := await session.get(db.Food, fdc_id)) is None:
        return None
    return FoodMatch(food.id, food.description, "alias")


async def candidates(
    session: AsyncSession, name: str, *, exclude_categories: Sequence[str] = ()
) -> list[Candidate]:
    """Trigram candidates for the name, ranked by word coverage."""
    query = " ".join(name.split()).strip()
    if not query:
        return []
    rows = await session.execute(
        _CANDIDATES_SQL,
        {"q": query.lower(), "excluded": list(exclude_categories), "limit": MAX_CANDIDATES},
    )
    return rank(query, [(fid, description) for fid, description in rows])


async def trigram_food(
    session: AsyncSession, name: str, *, exclude_categories: Sequence[str] = ()
) -> FoodMatch | None:
    winner = clear_winner(await candidates(session, name, exclude_categories=exclude_categories))
    return None if winner is None else FoodMatch(winner.food_id, winner.description, "trigram")
