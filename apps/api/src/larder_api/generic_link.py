"""On-demand linking of a product (or a CoFID food the batch linker left alone) to the generic
food it counts as, when it is added to a pantry: the reviewed vocabularies first (on the whole
name, then on its endings: "Pure Irish Butter" -> "butter", same category only), then the
trigram matcher's clear winner among generic foods (larder_api.foodmatch), each behind the
plausibility rules of larder_core.generic_links. Tried once per food: a miss is remembered
(`generic_method = "none"`) and left for the batch linker (larder-data link-generics).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from larder_api.foodmatch import NOT_GROCERIES, trigram_food
from larder_core.generic_links import Facts, name_endings, name_forms, plausible, vocabulary
from larder_core.names import normalise_name
from larder_core.receipts import clean_name
from larder_db.models import Food

_GENERIC_TYPES = ("foundation", "sr_legacy")


def _facts(food: Food) -> Facts:
    return Facts(food.category, food.kcal, food.protein_g, food.fat_g)


async def ensure_generic(session: AsyncSession, food: Food) -> None:
    """Link `food` if it can be and hasn't been tried; the caller commits."""
    if food.source == "usda" or food.generic_food_id is not None or food.generic_method:
        return
    name = clean_name(food.description) or normalise_name(food.description)
    if food.brand:
        brand = set(normalise_name(food.brand).split())
        name = " ".join(w for w in name.split() if w not in brand) or name
    names = vocabulary()
    whole = [names[f] for f in name_forms(food.description, food.brand) if f in names]
    endings = [names[f] for f in name_endings(name) if f in names]
    for ids, same_category in ((whole, False), (endings, True)):
        for generic in await _generics(session, ids):
            if plausible(_facts(food), _facts(generic), reviewed=True, same_category=same_category):
                food.generic_food_id, food.generic_method = generic.id, "curated"
                return
    match = await trigram_food(session, name, exclude_categories=NOT_GROCERIES)
    found = await _generics(session, [match.food_id]) if match is not None else []
    if found and plausible(_facts(food), _facts(found[0]), reviewed=False):
        food.generic_food_id, food.generic_method = found[0].id, "trigram"
    else:
        food.generic_method = "none"


async def _generics(session: AsyncSession, ids: list[int]) -> list[Food]:
    if not ids:
        return []
    rows = await session.scalars(
        select(Food).where(
            Food.id.in_(ids), Food.data_type.in_(_GENERIC_TYPES), Food.generic_food_id.is_(None)
        )
    )
    by_id = {f.id: f for f in rows}
    return [by_id[i] for i in dict.fromkeys(ids) if i in by_id]
