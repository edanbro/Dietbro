"""Resolve every recipe ingredient line to (food, grams) and compute recipe nutrition."""

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from larder_core.aliases import load_aliases
from larder_core.names import normalise_name
from larder_core.nutrition import Nutrients, estimate_servings, total
from larder_core.quantities import Portion, grams_for
from larder_core.units import parse_measure
from larder_data import matching
from larder_data.embeddings import Embedder
from larder_data.matching import Match, Method
from larder_db.models import Food, FoodPortion, IngredientMatch, Recipe, RecipeIngredient

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolveStats:
    names: int
    matched_names: int
    lines: int
    recipes_complete: int


async def match_names(
    session: AsyncSession,
    names: set[str],
    embedder: Embedder,
    threshold: float = matching.ACCEPT_THRESHOLD,
    *,
    use_cache: bool = True,
) -> dict[str, Match]:
    """Alias table first, then cached results, then retrieval + rerank for the rest."""
    aliases = load_aliases()
    cached = (
        {
            m.name: Match(m.food_id, cast(Method, m.method), m.score)
            for m in await session.scalars(
                select(IngredientMatch).where(
                    IngredientMatch.name.in_(names), IngredientMatch.model == embedder.model
                )
            )
        }
        if use_cache
        else {}
    )
    out: dict[str, Match] = {}
    todo: list[str] = []
    for name in sorted(names):
        if name in aliases:
            out[name] = Match(aliases[name], "alias", 1.0)
        elif name in cached and cached[name].method != "alias":
            out[name] = cached[name]
        elif name:
            todo.append(name)

    vectors = embedder.embed([matching.rewrite(n) for n in todo]) if todo else []
    for name, vector in zip(todo, vectors, strict=True):
        found = await matching.rank(session, name, vector)
        if found is not None and found[1] >= threshold:
            out[name] = Match(found[0].food_id, "embedding", found[1])
        else:
            out[name] = Match(None, "unmatched", found[1] if found else None)
    logger.info("matched %d names (%d new)", len(out), len(todo))

    if out:
        stmt = insert(IngredientMatch).values(
            [
                {
                    "name": n,
                    "food_id": m.food_id,
                    "method": m.method,
                    "score": m.score,
                    "model": embedder.model,
                }
                for n, m in out.items()
            ]
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[IngredientMatch.name],
                set_={
                    c: getattr(stmt.excluded, c) for c in ("food_id", "method", "score", "model")
                },
            )
        )
    return out


async def resolve_all(
    session: AsyncSession, embedder: Embedder, *, use_cache: bool = True
) -> ResolveStats:
    lines = (
        await session.execute(
            select(
                RecipeIngredient.id,
                RecipeIngredient.recipe_id,
                RecipeIngredient.raw_name,
                RecipeIngredient.raw_measure,
            )
        )
    ).all()
    names = {normalise_name(raw) for _, _, raw, _ in lines}
    matches = await match_names(session, names, embedder, use_cache=use_cache)

    food_ids = {m.food_id for m in matches.values() if m.food_id is not None}
    portions: dict[int, list[Portion]] = defaultdict(list)
    for p in await session.scalars(select(FoodPortion).where(FoodPortion.food_id.in_(food_ids))):
        portions[p.food_id].append(Portion(p.amount, p.unit, p.qualifier, p.grams))
    foods = {f.id: f for f in await session.scalars(select(Food).where(Food.id.in_(food_ids)))}

    updates: list[dict[str, object]] = []
    by_recipe: dict[int, list[tuple[int | None, float | None]]] = defaultdict(list)
    for line_id, recipe_id, raw_name, raw_measure in lines:
        name = normalise_name(raw_name)
        match = matches.get(name, Match(None, "unmatched"))
        grams = None
        if match.food_id is not None:
            grams = grams_for(
                parse_measure(raw_measure),
                portions[match.food_id],
                name,
                foods[match.food_id].category,
            )
        updates.append(
            {
                "id": line_id,
                "food_id": match.food_id,
                "grams": grams,
                "match_method": match.method if match.food_id is not None else None,
                "match_score": match.score,
            }
        )
        by_recipe[recipe_id].append((match.food_id, grams))
    if updates:
        await session.execute(update(RecipeIngredient), updates)

    categories = {
        rid: cat for rid, cat in (await session.execute(select(Recipe.id, Recipe.category))).all()
    }
    recipe_updates: list[dict[str, object]] = []
    for recipe_id, items in by_recipe.items():
        recipe_updates.append(
            {"id": recipe_id, **recipe_nutrition(items, foods, categories.get(recipe_id))}
        )
    if recipe_updates:
        await session.execute(update(Recipe), recipe_updates)
    await session.commit()

    complete = sum(1 for r in recipe_updates if r["nutrition_complete"])
    return ResolveStats(
        names=len(names),
        matched_names=sum(1 for m in matches.values() if m.food_id is not None),
        lines=len(lines),
        recipes_complete=complete,
    )


def food_nutrients(food: Food) -> Nutrients | None:
    if food.kcal is None:
        return None
    return Nutrients(*(getattr(food, f) or 0.0 for f in Nutrients.FIELDS))


# Typical energy of one portion by recipe category, for sources without serving counts.
KCAL_PER_SERVING = {"Dessert": 350.0, "Side": 250.0, "Starter": 300.0, "Breakfast": 450.0}


def recipe_nutrition(
    items: list[tuple[int | None, float | None]],
    foods: dict[int, Food],
    category: str | None = None,
) -> dict[str, object]:
    """Per-serving nutrition, or nulls when any line lacks a food, grams or energy data."""
    resolved: list[tuple[Nutrients, float]] = []
    out: dict[str, object] = {"servings_estimated": False, "nutrition_complete": False}
    for food_id, grams in items:
        n = food_nutrients(foods[food_id]) if food_id is not None else None
        if n is None or grams is None:
            return out | dict.fromkeys(Nutrients.FIELDS) | {"servings": None}
        resolved.append((n, grams))
    totals = total(resolved)
    servings = estimate_servings(totals.kcal, KCAL_PER_SERVING.get(category or "", 650.0))
    per = totals.per_serving(servings)
    out |= {f: getattr(per, f) for f in Nutrients.FIELDS}
    out |= {"servings": servings, "servings_estimated": True, "nutrition_complete": True}
    return out
