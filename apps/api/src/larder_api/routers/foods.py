"""Food search (type-ahead for pantry entry and food preferences) and food details.

Foods come from USDA (generic foods and survey foods), UK CoFID and Open Food Facts products
(see larder_db.models.Food). Search ranks, in order: curated names first on the first page
("onion" -> "Onions, raw"); then foods matching every word (full-text, with British/Irish
synonyms: "crisps" also finds "potato chips"), generic foods before packaged products, names
starting with the query, the user's regional foods first (CoFID in Ireland and the UK); then
partial matches by trigram similarity. Products are only shown for queries of 3+ characters
and when sold in the user's country.
"""

import re
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select, text

from larder_api.auth import CurrentUser
from larder_api.db import Session
from larder_api.foodmatch import NOT_GROCERIES
from larder_api.schemas import FoodDetail, FoodSummary, FoodUnit
from larder_core.aliases import load_aliases
from larder_core.allergens import Allergen
from larder_core.names import normalise_name
from larder_core.quantities import Portion, count_portions, density
from larder_core.receipts import load_receipt_foods
from larder_core.regions import region_for
from larder_core.synonyms import search_terms
from larder_core.tagging import FoodFacts, FoodTags, tag_any
from larder_core.units import MASS_UNITS
from larder_db.models import Food, FoodPortion

router = APIRouter(prefix="/foods", tags=["foods"])

# Products (Open Food Facts) are imported for these; other countries see generic foods only.
PRODUCT_COUNTRIES = frozenset({"IE", "GB"})
# Generic sources a region's shoppers recognise first (CoFID names are British/Irish English).
REGIONAL_TYPES: dict[str, tuple[str, ...]] = {"IE": ("cofid",), "GB": ("cofid",)}

_SEARCH_SQL = text(
    """
    SELECT f.id, f.description, f.category, f.kcal, f.brand, f.source,
           (p.tsq IS NOT NULL AND f.search_tsv @@ p.tsq) AS every_word
    FROM foods f,
         (SELECT CASE WHEN :tsq = '' THEN NULL ELSE to_tsquery('english', :tsq) END AS tsq) p
    WHERE f.kcal IS NOT NULL
      AND f.retired_at IS NULL
      AND NOT (f.source <> 'off' AND coalesce(f.category, '') = ANY(:excluded))
      AND NOT (f.id = ANY(:skip))
      AND (:products OR f.source <> 'off')
      AND (f.source <> 'off' OR f.countries && CAST(:countries AS varchar[]))
      AND ((p.tsq IS NOT NULL AND f.search_tsv @@ p.tsq)
           OR f.description ILIKE '%' || :q || '%' OR :q <% f.description
           OR f.description ILIKE '%' || :q2 || '%' OR :q2 <% f.description)
    ORDER BY every_word DESC,
             (f.source = 'off'),
             (f.description ILIKE :q || '%' OR f.description ILIKE :q2 || '%') DESC,
             (f.data_type = ANY(:preferred)) DESC,
             greatest(word_similarity(:q, f.description), word_similarity(:q2, f.description)) DESC,
             (f.data_type = 'sr_legacy') DESC,
             length(f.description), f.id
    LIMIT :limit OFFSET :offset
    """
)
_WORD = re.compile(r"[a-z0-9]+")
_PANTRY_MASS_UNITS = ("g", "kg")
_PANTRY_VOLUME_UNITS = ("ml", "l", "tsp", "tbsp", "cup")
_PACK_UNITS = ("packet", "serving")

ATTRIBUTION = {
    "usda": "USDA FoodData Central (public domain)",
    "cofid": "McCance and Widdowson's Composition of Foods 2021 (Open Government Licence v3.0)",
    "off": "Open Food Facts contributors (Open Database License)",
}


def tsquery(*queries: str) -> str:
    """Every word of a query (the last one as a prefix: type-ahead), queries OR-ed."""
    parts: list[str] = []
    for q in dict.fromkeys(queries):
        words = _WORD.findall(q.casefold())
        if words:
            words[-1] += ":*"
            parts.append("(" + " & ".join(words) + ")")
    return " | ".join(parts)


@router.get("/search", operation_id="searchFoods")
async def search(
    user: CurrentUser,
    session: Session,
    q: Annotated[str, Query(min_length=2, max_length=80)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=200)] = 0,
    scope: Annotated[
        Literal["all", "generic"],
        Query(description="generic: foods only, no packaged products (allergies, preferences)"),
    ] = "all",
) -> list[FoodSummary]:
    """A page of foods for `q`; a full page means there may be more (next `offset`)."""
    query = q.strip()
    country = region_for(user.country).country
    # Curated names lead page one; every page skips them, so offsets stay consistent.
    named = await _named(session, normalise_name(query), limit)
    ordered: dict[int, FoodSummary] = {}
    if offset == 0:
        for food in named:
            ordered.setdefault(food.id, summary(food))
    terms = search_terms(query)
    rows = await session.execute(
        _SEARCH_SQL,
        {
            "q": query,
            "q2": terms,
            "tsq": tsquery(query, terms),
            "excluded": list(NOT_GROCERIES),
            "skip": [f.id for f in named],
            "products": scope == "all" and len(query) >= 3 and country in PRODUCT_COUNTRIES,
            "countries": [country],
            "preferred": list(REGIONAL_TYPES.get(country, ("sr_legacy",))),
            "limit": limit - len(ordered),
            "offset": max(0, offset - len(named)),
        },
    )
    for fid, description, category, kcal, brand, source, _ in rows:
        ordered.setdefault(
            fid,
            FoodSummary(
                id=fid,
                description=description,
                category=category,
                kcal=kcal,
                brand=brand,
                source=source,
                kind="product" if source == "off" else "food",
            ),
        )
    return list(ordered.values())[:limit]


async def _named(session: Session, name: str, limit: int) -> list[Food]:
    """Foods the reviewed vocabularies name: exact names, then names starting with it."""
    names = load_aliases() | load_receipt_foods()
    ids = [fid for n, fid in names.items() if n == name] + [
        fid for n, fid in sorted(names.items()) if n.startswith(name) and n != name
    ]
    ids = list(dict.fromkeys(ids))[: max(0, limit // 2)]
    if not ids:
        return []
    by_id = {f.id: f for f in await session.scalars(select(Food).where(Food.id.in_(ids)))}
    return [by_id[i] for i in ids if i in by_id]


@router.get("/{food_id}", operation_id="getFood")
async def get_food(food_id: int, _user: CurrentUser, session: Session) -> FoodDetail:
    food = await session.get(Food, food_id)
    if food is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "food not found")
    return await food_detail(session, food)


async def food_detail(session: Session, food: Food) -> FoodDetail:
    generic = await session.get(Food, food.generic_food_id) if food.generic_food_id else None
    portions = await food_portions(session, food)
    ingredients = (
        await session.scalar(select(Food.ingredients_text).where(Food.id == food.id))
        if food.source != "usda"
        else None
    )
    tags = food_tags(food, generic, ingredients)
    return FoodDetail(
        **summary(food).model_dump(),
        units=units_for(portions, food.description.lower()),
        barcode=food.barcode,
        allergens=sorted(tags.allergens),
        may_contain=sorted(Allergen(a) for a in food.traces_declared or ()),
        counts_as=summary(generic) if generic is not None else None,
        attribution=ATTRIBUTION.get(food.source, food.source),
    )


def food_tags(food: Food, generic: Food | None, ingredients: str | None = None) -> FoodTags:
    """Allergen and diet tags for any food, at least as cautious as its generic's.
    `ingredients`: the label's ingredient list (a deferred column: loaded by the caller)."""
    generic_tags = food_tags(generic, None) if generic is not None else None
    return tag_any(
        FoodFacts(
            id=food.id,
            description=food.description,
            category=food.category,
            source=food.source,
            source_category=food.source_category,
            brand=food.brand,
            ingredients=ingredients,
            declared=frozenset(Allergen(a) for a in food.allergens_declared or ()),
            traces=frozenset(Allergen(a) for a in food.traces_declared or ()),
        ),
        generic_tags,
    )


async def food_portions(session: Session, food: Food) -> list[Portion]:
    """A food's portions plus its generic's for units it lacks ("1 cup" of a branded milk)."""
    portions = await load_portions(session, food.id)
    if food.generic_food_id is not None:
        own = {p.unit for p in portions}
        generic = await load_portions(session, food.generic_food_id)
        portions += [p for p in generic if p.unit not in own]
    return portions


async def load_portions(session: Session, food_id: int) -> list[Portion]:
    rows = await session.scalars(select(FoodPortion).where(FoodPortion.food_id == food_id))
    return [Portion(p.amount, p.unit, p.qualifier, p.grams) for p in rows]


def units_for(portions: list[Portion], name: str) -> list[FoodUnit]:
    """Units offered when adding this food: a product's packet and serving first, mass always,
    volume when a density is known, and the food's own count units (clove, large...)."""
    units: list[FoodUnit] = []
    for unit in _PACK_UNITS:
        pack = next((p for p in portions if p.unit == unit and p.amount > 0), None)
        if pack is not None:
            units.append(FoodUnit(unit=unit, grams_each=round(pack.grams / pack.amount, 1)))
    units += [FoodUnit(unit=u, grams_each=MASS_UNITS[u]) for u in _PANTRY_MASS_UNITS]
    if density(portions) is not None:
        units += [FoodUnit(unit=u) for u in _PANTRY_VOLUME_UNITS]
    seen: set[str] = {u.unit for u in units}
    for p in count_portions(portions):
        if p.unit not in seen:
            seen.add(p.unit)
            units.append(FoodUnit(unit=p.unit, grams_each=round(p.per_unit, 1)))
    return units


def summary(food: Food) -> FoodSummary:
    return FoodSummary(
        id=food.id,
        description=food.description,
        category=food.category,
        kcal=food.kcal,
        brand=food.brand,
        source=food.source,
        kind="product" if food.source == "off" else "food",
    )
