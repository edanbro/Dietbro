from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from larder_db.models import EMBEDDING_DIM, Base, Food, FoodEmbedding, Recipe, RecipeIngredient
from larder_db.testing import alembic_config


def test_migrations_round_trip(migrated_database_url: str) -> None:
    config = alembic_config(migrated_database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")


async def test_models_match_migrations(migrated_database_url: str) -> None:
    """Autogenerate against the migrated DB finds nothing: models and migrations agree."""

    def diff(conn: Connection) -> list[Any]:
        return compare_metadata(MigrationContext.configure(conn), Base.metadata)

    engine = create_async_engine(migrated_database_url)
    async with engine.connect() as conn:
        changes = await conn.run_sync(diff)
    await engine.dispose()
    assert changes == []


async def test_recipe_with_ingredients_round_trips(db_session: AsyncSession) -> None:
    db_session.add(Food(id=1, description="Onions, raw", data_type="sr_legacy", kcal=40))
    recipe = Recipe(source="mealdb", source_id="1", name="Soup")
    recipe.ingredients = [
        RecipeIngredient(position=0, raw_name="Onion", raw_measure="1", food_id=1, grams=110),
        RecipeIngredient(position=1, raw_name="Unobtainium", raw_measure="pinch"),
    ]
    db_session.add(recipe)
    await db_session.commit()

    loaded = (await db_session.scalars(select(Recipe))).one()
    await db_session.refresh(loaded, ["ingredients"])
    assert [(i.raw_name, i.food_id) for i in loaded.ingredients] == [
        ("Onion", 1),
        ("Unobtainium", None),
    ]


async def test_recipe_source_is_unique(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Recipe(source="mealdb", source_id="1", name="A"),
            Recipe(source="mealdb", source_id="1", name="B"),
        ]
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_vector_nearest_neighbour(db_session: AsyncSession) -> None:
    def unit(i: int) -> list[float]:
        v = [0.0] * EMBEDDING_DIM
        v[i] = 1.0
        return v

    db_session.add_all(
        [Food(id=i, description=f"food {i}", data_type="sr_legacy") for i in (1, 2, 3)]
    )
    await db_session.flush()
    db_session.add_all(
        [FoodEmbedding(food_id=i, model="test", embedding=unit(i)) for i in (1, 2, 3)]
    )
    await db_session.commit()

    query = unit(2)
    nearest = await db_session.scalar(
        select(FoodEmbedding.food_id).order_by(FoodEmbedding.embedding.cosine_distance(query))
    )
    assert nearest == 2
    assert await db_session.scalar(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    )
