"""Link regional and branded foods to the generic USDA food they count as (`generic_food_id`):
"Bacon rashers, back, raw" (CoFID) -> "Pork, cured, bacon, unprepared". The planner then counts
a pantry item of it toward recipes that use the generic, and prices, shelf life and portions
fall back to the generic's.

Survey foods (FNDDS) are linked at import from their dominant ingredient (larder_data.fndds).
Here, in batch (CoFID; products too, but slowly: the API links a product on demand when it is
added to a pantry): first the reviewed vocabularies, then the ingredient matcher's ranking over
generic foods, each behind the plausibility rules in larder_core.generic_links. Unlinked is
fine: the food is still searchable and loggable, it just doesn't stand in for a generic.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from larder_core.generic_links import Facts, name_forms, plausible, vocabulary
from larder_core.names import normalise_name
from larder_core.receipts import clean_name
from larder_data import matching
from larder_data.embeddings import Embedder
from larder_db.models import Food

__all__ = ["ACCEPT", "LinkStats", "count_links", "link_generics"]

logger = logging.getLogger(__name__)

_BATCH = 256
ACCEPT = 0.86  # matching.score, a little below the resolver's: the plausibility rules back it up


@dataclass(slots=True)
class LinkStats:
    considered: int = 0
    linked: int = 0


def _query(description: str, brand: str | None) -> str:
    text = clean_name(description) or normalise_name(description)
    if brand:
        words = set(normalise_name(brand).split())
        text = " ".join(w for w in text.split() if w not in words) or text
    return matching.rewrite(text)


def _facts(food: Food) -> Facts:
    return Facts(food.category, food.kcal, food.protein_g, food.fat_g)


async def link_generics(
    session: AsyncSession,
    embedder: Embedder,
    sources: Sequence[str] = ("cofid", "off"),
    *,
    limit: int | None = None,
    retry: bool = False,
) -> LinkStats:
    """Link unlinked, unretired foods of `sources`; returns how many were linked. Foods tried
    before without a match are skipped unless `retry`."""
    stmt = (
        select(Food)
        .where(
            Food.source.in_(sources),
            Food.generic_food_id.is_(None),
            Food.retired_at.is_(None),
            # "none": tried before without a match
            Food.generic_method.is_(None) | (Food.generic_method == "none" if retry else False),
        )
        .order_by(Food.id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    foods = (await session.scalars(stmt)).all()
    stats = LinkStats(considered=len(foods))
    generics = await _generic_facts(session)
    names = vocabulary()
    for i in range(0, len(foods), _BATCH):
        batch = foods[i : i + _BATCH]
        queries = [_query(f.description, f.brand) for f in batch]
        vectors = embedder.embed(queries)
        for food, query, vector in zip(batch, queries, vectors, strict=True):
            target, method = None, "embedding"
            for form in name_forms(food.description, food.brand):
                known = names.get(form)
                facts = generics.get(known) if known is not None else None
                if facts is not None and plausible(_facts(food), facts, reviewed=True):
                    target, method = known, "curated"
                    break
            if target is None:
                found = matching.best(query, await matching.candidates(session, query, vector))
                if found is not None and found[1] >= ACCEPT:
                    facts = generics.get(found[0].food_id)
                    if facts is not None and plausible(_facts(food), facts, reviewed=False):
                        target = found[0].food_id
            await session.execute(
                update(Food)
                .where(Food.id == food.id)
                .values(
                    generic_food_id=target,
                    generic_method=method if target is not None else "none",
                )
            )
            stats.linked += target is not None
        await session.commit()
        logger.info("linked %d of %d foods", stats.linked, min(i + _BATCH, len(foods)))
    return stats


async def _generic_facts(session: AsyncSession) -> dict[int, Facts]:
    rows = await session.execute(
        select(Food.id, Food.category, Food.kcal, Food.protein_g, Food.fat_g).where(
            Food.data_type.in_(matching.RESOLVER_TYPES), Food.generic_food_id.is_(None)
        )
    )
    return {r[0]: Facts(r[1], r[2], r[3], r[4]) for r in rows}


async def count_links(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(
        select(Food.source, func.count(Food.generic_food_id)).group_by(Food.source)
    )
    return dict(rows.tuples().all())
