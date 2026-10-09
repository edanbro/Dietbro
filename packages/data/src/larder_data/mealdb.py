"""TheMealDB recipe importer (https://www.themealdb.com/api.php).

The free test key "1" is for development/education; production use needs a supporter key
(MEALDB_API_KEY). Raw API responses are cached under the cache dir so imports are repeatable.
"""

import json
import logging
import os
import string
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_db.models import Recipe, RecipeIngredient, RecipeTag

logger = logging.getLogger(__name__)

SOURCE = "mealdb"
MAX_INGREDIENTS = 20


def api_url() -> str:
    return f"https://www.themealdb.com/api/json/v1/{os.environ.get('MEALDB_API_KEY', '1')}/"


@dataclass(frozen=True, slots=True)
class IngredientLine:
    position: int
    name: str
    measure: str


@dataclass(frozen=True, slots=True)
class RecipeDraft:
    source_id: str
    name: str
    category: str | None
    cuisine: str | None
    instructions: str
    image_url: str | None
    source_url: str | None
    tags: tuple[str, ...]
    ingredients: tuple[IngredientLine, ...]
    servings: int | None = None  # explicit count (curated); None = estimate from energy


async def fetch_meals(
    client: httpx.AsyncClient, cache_dir: Path, *, refresh: bool = False
) -> list[dict[str, Any]]:
    """All meals, via search-by-first-letter (the API has no list-all). Cached per letter."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    meals: dict[str, dict[str, Any]] = {}
    for letter in string.ascii_lowercase:
        path = cache_dir / f"search_{letter}.json"
        if refresh or not path.exists():
            response = await client.get(api_url() + "search.php", params={"f": letter})
            response.raise_for_status()
            path.write_text(response.text)
        payload: dict[str, Any] = json.loads(path.read_text())
        found: list[dict[str, Any]] = payload.get("meals") or []
        for meal in found:
            meals[meal["idMeal"]] = meal
    logger.info("fetched %d meals", len(meals))
    return list(meals.values())


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_meal(meal: dict[str, Any]) -> RecipeDraft:
    lines: list[IngredientLine] = []
    for i in range(1, MAX_INGREDIENTS + 1):
        name = _clean(meal.get(f"strIngredient{i}"))
        if name:
            lines.append(IngredientLine(len(lines), name, _clean(meal.get(f"strMeasure{i}"))))
    tags = tuple(
        dict.fromkeys(
            t.strip().lower() for t in _clean(meal.get("strTags")).split(",") if t.strip()
        )
    )
    return RecipeDraft(
        source_id=str(meal["idMeal"]),
        name=_clean(meal.get("strMeal")),
        category=_clean(meal.get("strCategory")) or None,
        cuisine=_clean(meal.get("strArea")) or _clean(meal.get("strCountry")) or None,
        instructions=_clean(meal.get("strInstructions")),
        image_url=_clean(meal.get("strMealThumb")) or None,
        source_url=_clean(meal.get("strSource")) or None,
        tags=tags,
        ingredients=tuple(lines),
    )


async def load_recipes(
    session: AsyncSession, drafts: Iterable[RecipeDraft], source: str = SOURCE
) -> int:
    """Insert or update recipes by (source, source_id). Ingredient lines are replaced, so
    their resolution must be recomputed afterwards."""
    drafts = list(drafts)
    existing = {
        r.source_id: r
        for r in await session.scalars(
            select(Recipe)
            .where(Recipe.source == source)
            .options(selectinload(Recipe.ingredients), selectinload(Recipe.tags))
        )
    }
    for d in drafts:
        recipe = existing.get(d.source_id)
        if recipe is None:
            recipe = Recipe(source=source, source_id=d.source_id)
        else:
            # Delete old lines first: (recipe_id, position) and (recipe_id, tag) are unique.
            recipe.ingredients.clear()
            recipe.tags.clear()
            await session.flush()
        recipe.name = d.name
        recipe.category = d.category
        recipe.cuisine = d.cuisine
        recipe.instructions = d.instructions
        recipe.image_url = d.image_url
        recipe.source_url = d.source_url
        recipe.nutrition_complete = False
        if d.servings is not None:
            recipe.servings = d.servings
            recipe.servings_estimated = False
        recipe.ingredients = [
            RecipeIngredient(position=line.position, raw_name=line.name, raw_measure=line.measure)
            for line in d.ingredients
        ]
        recipe.tags = [RecipeTag(tag=t) for t in d.tags]
        session.add(recipe)
    await session.commit()
    return len(drafts)
