"""Text embeddings (local fastembed / ONNX; see docs/adr/0005-local-embeddings.md)."""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_db.models import EMBEDDING_DIM, Food, FoodEmbedding, Recipe, RecipeEmbedding

logger = logging.getLogger(__name__)

MODEL_NAME = "BAAI/bge-small-en-v1.5"
_BATCH = 512


class Embedder(Protocol):
    @property
    def model(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Unit-length vectors of length EMBEDDING_DIM, one per text."""
        ...


class FastEmbedder:
    """bge-small-en-v1.5 via fastembed. The ~65 MB model downloads on first use."""

    def __init__(self, cache_dir: Path) -> None:
        from fastembed import TextEmbedding  # heavy import; only when actually embedding

        self._model = TextEmbedding(MODEL_NAME, cache_dir=str(cache_dir))

    @property
    def model(self) -> str:
        return MODEL_NAME

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = [v.tolist() for v in self._model.embed(list(texts), batch_size=256)]
        assert all(len(v) == EMBEDDING_DIM for v in vectors)
        return vectors


def food_text(description: str) -> str:
    """Text embedded for a USDA food. Descriptions are already 'Onions, raw'-style lists."""
    return description


async def embed_foods(session: AsyncSession, embedder: Embedder) -> int:
    """(Re)embed every food that has no embedding from the current model."""
    have = select(FoodEmbedding.food_id).where(FoodEmbedding.model == embedder.model)
    foods = (
        await session.execute(select(Food.id, Food.description).where(Food.id.not_in(have)))
    ).all()
    await session.execute(delete(FoodEmbedding).where(FoodEmbedding.model != embedder.model))
    for i in range(0, len(foods), _BATCH):
        batch = foods[i : i + _BATCH]
        vectors = embedder.embed([food_text(d) for _, d in batch])
        stmt = insert(FoodEmbedding).values(
            [
                {"food_id": fid, "model": embedder.model, "embedding": v}
                for (fid, _), v in zip(batch, vectors, strict=True)
            ]
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[FoodEmbedding.food_id],
                set_={"model": stmt.excluded.model, "embedding": stmt.excluded.embedding},
            )
        )
        logger.info("embedded %d/%d foods", min(i + _BATCH, len(foods)), len(foods))
    await session.commit()
    return len(foods)


def recipe_text(recipe: Recipe, ingredient_names: list[str]) -> str:
    parts = [recipe.name, recipe.category or "", recipe.cuisine or ""]
    parts.append(", ".join(t.tag for t in recipe.tags))
    parts.append("Ingredients: " + ", ".join(ingredient_names))
    return ". ".join(p for p in parts if p)


async def embed_recipes(session: AsyncSession, embedder: Embedder) -> int:
    recipes = (
        await session.scalars(
            select(Recipe).options(selectinload(Recipe.tags), selectinload(Recipe.ingredients))
        )
    ).all()
    texts = [recipe_text(r, [i.raw_name for i in r.ingredients]) for r in recipes]
    for i in range(0, len(recipes), _BATCH):
        batch = recipes[i : i + _BATCH]
        vectors = embedder.embed(texts[i : i + _BATCH])
        stmt = insert(RecipeEmbedding).values(
            [
                {"recipe_id": r.id, "model": embedder.model, "embedding": v}
                for r, v in zip(batch, vectors, strict=True)
            ]
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[RecipeEmbedding.recipe_id],
                set_={"model": stmt.excluded.model, "embedding": stmt.excluded.embedding},
            )
        )
    await session.commit()
    return len(recipes)
