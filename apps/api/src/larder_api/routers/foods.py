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
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from larder_api.auth import CurrentUser
from larder_api.barcodes import Limits, OffClient, OffUnavailable, get_limits, get_off_client
from larder_api.db import Session
from larder_api.foodmatch import NOT_GROCERIES
from larder_api.generic_link import ensure_generic, link_by_category
from larder_api.schemas import FoodDetail, FoodSummary, FoodUnit, NutritionGrade, Problems
from larder_core.aliases import load_aliases
from larder_core.allergens import Allergen
from larder_core.categories import off_category
from larder_core.names import normalise_name
from larder_core.nutrigrade import NutriInput, grade
from larder_core.off import OffProduct, normalise_barcode, parse_product
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
    SELECT f.id, f.description, f.category, f.kcal, f.brand, f.source, f.image_url,
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
    for fid, description, category, kcal, brand, source, image_url, _ in rows:
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
                image_url=image_url,
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


_BARCODE_PROBLEMS: dict[int | str, dict[str, Any]] = {
    code: {"model": Problems}
    for code in (
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_429_TOO_MANY_REQUESTS,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )
}
NOT_FOUND = "We don't know that barcode yet. Search for the food by name instead."


@router.get("/barcode/{code}", operation_id="lookupBarcode", responses=_BARCODE_PROBLEMS)
async def lookup_barcode(
    code: str,
    user: CurrentUser,
    session: Session,
    off: Annotated[OffClient | None, Depends(get_off_client)],
    limits: Annotated[Limits, Depends(get_limits)],
) -> FoodDetail:
    """A product by its barcode (EAN-13, EAN-8, UPC-A): from the catalogue, else from Open Food
    Facts (stored, so the next scan is local). Only the barcode leaves the app."""
    barcode = normalise_barcode(code)
    if barcode is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, ["That isn't a valid product barcode."]
        )
    food = await session.scalar(select(Food).where(Food.barcode == barcode))
    if food is not None:
        if food.retired_at is not None:
            food.retired_at = None  # someone still has it: it's sold somewhere
            await session.commit()
        return await food_detail(session, food)
    if off is None or await limits.known_missing(barcode):
        raise HTTPException(status.HTTP_404_NOT_FOUND, [NOT_FOUND])
    if not await limits.take_user(user.id):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ["That's a lot of new barcodes for one hour. Search by name for now."],
        )
    if not await limits.take_global():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ["The product database is busy. Try again in a minute."],
            headers={"Retry-After": "60"},
        )
    try:
        fields = await off.product(barcode)
    except OffUnavailable as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ["Couldn't reach the product database. Try again shortly."],
            headers={"Retry-After": "60"},
        ) from exc
    product = parse_product(fields) if fields is not None else None
    if product is None:
        await limits.remember_missing(barcode)
        raise HTTPException(status.HTTP_404_NOT_FOUND, [NOT_FOUND])
    food = await store_product(session, product, barcode, region_for(user.country).country)
    return await food_detail(session, food)


async def store_product(session: Session, p: OffProduct, barcode: str, country: str) -> Food:
    """Keep a looked-up product (it was scanned here, so it's sold in the user's country)."""
    existing = await session.scalar(
        select(Food).where(Food.source == "off", Food.source_id == p.code)
    )
    food_id = (
        existing.id
        if existing
        else await session.scalar(text("SELECT nextval('foods_local_id_seq')"))
    )
    assert food_id is not None
    food = existing or Food(id=food_id, source="off", source_id=p.code, data_type="branded")
    food.description = p.name
    food.brand = p.brand
    food.barcode = barcode
    food.category = off_category(p.categories)
    food.source_category = p.categories[-1] if p.categories else None
    food.countries = sorted({*p.countries, country})
    food.allergens_declared = sorted(a.value for a in p.allergens) or None
    food.traces_declared = sorted(a.value for a in p.traces) or None
    food.ingredients_text = p.ingredients[:4000] if p.ingredients else None
    food.origin = existing.origin if existing else "lookup"
    food.image_url = p.image_url
    food.off_grade = p.grade
    food.retired_at = None
    food.kcal, food.protein_g, food.fat_g, food.carbs_g = p.kcal, p.protein_g, p.fat_g, p.carbs_g
    food.fiber_g, food.sugars_g, food.sat_fat_g, food.sodium_mg = (
        p.fiber_g,
        p.sugars_g,
        p.sat_fat_g,
        p.sodium_mg,
    )
    if existing is None:
        session.add(food)
        session.add_all(
            FoodPortion(food_id=food_id, amount=1, unit=unit, grams=grams)
            for unit, grams in p.portions
        )
    await link_by_category(session, food, p.categories)
    await ensure_generic(session, food)
    try:
        await session.commit()
    except IntegrityError:  # scanned twice at once: the other request stored it
        await session.rollback()
        stored = await session.scalar(select(Food).where(Food.barcode == barcode))
        if stored is None:
            raise
        return stored
    return food


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
        grade=food_grade(food),
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
        image_url=food.image_url,
    )


# Generic foods of these groups are all fruit, vegetables or legumes (Nutri-Score's "fvl").
FRUIT_VEG_CATEGORIES = frozenset(
    {
        "Fruits and Fruit Juices",
        "Vegetables and Vegetable Products",
        "Legumes and Legume Products",
    }
)


def food_grade(food: Food) -> NutritionGrade | None:
    """A product's own Nutri-Score when Open Food Facts has one, else ours (Nutri-Score method)
    from its nutrients per 100 g. Products don't say how much fruit or veg they hold, so only
    generic foods of those groups count it."""
    if food.off_grade:
        return cast(NutritionGrade, food.off_grade.upper())
    fruit_veg = 100.0 if food.source != "off" and food.category in FRUIT_VEG_CATEGORIES else 0.0
    found = grade(
        NutriInput(
            kcal=food.kcal,
            sugars_g=food.sugars_g,
            sat_fat_g=food.sat_fat_g,
            sodium_mg=food.sodium_mg,
            protein_g=food.protein_g,
            fiber_g=food.fiber_g,
            fruit_veg_pct=fruit_veg,
        ),
        category=food.category,
        description=food.description,
    )
    return cast(NutritionGrade | None, found)
