"""USDA food search (type-ahead for pantry entry and food preferences) and food details."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select, text

from larder_api.auth import CurrentUser
from larder_api.db import Session
from larder_api.schemas import FoodDetail, FoodSummary, FoodUnit
from larder_core.aliases import load_aliases
from larder_core.names import normalise_name
from larder_core.quantities import Portion, count_portions, density
from larder_core.units import MASS_UNITS
from larder_db.models import Food, FoodPortion

router = APIRouter(prefix="/foods", tags=["foods"])

# Not things you'd keep in a pantry.
_EXCLUDED_CATEGORIES = [
    "Baby Foods",
    "Fast Foods",
    "Restaurant Foods",
    "Meals, Entrees, and Side Dishes",
    "American Indian/Alaska Native Foods",
]
_SEARCH_SQL = text(
    """
    SELECT id, description, category, kcal
    FROM foods
    WHERE kcal IS NOT NULL
      AND NOT (coalesce(category, '') = ANY(:excluded))
      AND (description ILIKE '%' || :q || '%' OR :q <% description)
    ORDER BY word_similarity(:q, description) DESC, (data_type = 'sr_legacy') DESC,
             length(description), id
    LIMIT :limit
    """
)
_PANTRY_MASS_UNITS = ("g", "kg")
_PANTRY_VOLUME_UNITS = ("ml", "l", "tsp", "tbsp", "cup")


@router.get("/search", operation_id="searchFoods")
async def search(
    _user: CurrentUser,
    session: Session,
    q: Annotated[str, Query(min_length=2, max_length=80)],
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> list[FoodSummary]:
    """Curated ingredient names first ("onion" -> "Onions, raw"), then trigram matches."""
    name = normalise_name(q)
    aliases = load_aliases()
    alias_ids = [fid for n, fid in aliases.items() if n == name] + [
        fid for n, fid in sorted(aliases.items()) if n.startswith(name) and n != name
    ]
    ordered: dict[int, FoodSummary] = {}
    if alias_ids:
        rows = await session.scalars(select(Food).where(Food.id.in_(alias_ids[:limit])))
        by_id = {f.id: f for f in rows}
        for fid in alias_ids[:limit]:
            if (f := by_id.get(fid)) is not None:
                ordered.setdefault(fid, summary(f))
    rows = await session.execute(
        _SEARCH_SQL, {"q": q.strip(), "excluded": _EXCLUDED_CATEGORIES, "limit": limit}
    )
    for fid, description, category, kcal in rows:
        ordered.setdefault(
            fid, FoodSummary(id=fid, description=description, category=category, kcal=kcal)
        )
    return list(ordered.values())[:limit]


@router.get("/{food_id}", operation_id="getFood")
async def get_food(food_id: int, _user: CurrentUser, session: Session) -> FoodDetail:
    food = await session.get(Food, food_id)
    if food is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "food not found")
    portions = await load_portions(session, food_id)
    return FoodDetail(
        **summary(food).model_dump(), units=units_for(portions, food.description.lower())
    )


async def load_portions(session: Session, food_id: int) -> list[Portion]:
    rows = await session.scalars(select(FoodPortion).where(FoodPortion.food_id == food_id))
    return [Portion(p.amount, p.unit, p.qualifier, p.grams) for p in rows]


def units_for(portions: list[Portion], name: str) -> list[FoodUnit]:
    """Units offered when adding this food: mass always, volume when USDA gives a density,
    and the food's own count units (clove, large, fruit...) with their weights."""
    units = [FoodUnit(unit=u, grams_each=MASS_UNITS[u]) for u in _PANTRY_MASS_UNITS]
    if density(portions) is not None:
        units += [FoodUnit(unit=u) for u in _PANTRY_VOLUME_UNITS]
    seen: set[str] = set()
    for p in count_portions(portions):
        if p.unit not in seen:
            seen.add(p.unit)
            units.append(FoodUnit(unit=p.unit, grams_each=round(p.per_unit, 1)))
    return units


def summary(food: Food) -> FoodSummary:
    return FoodSummary(
        id=food.id, description=food.description, category=food.category, kcal=food.kcal
    )
