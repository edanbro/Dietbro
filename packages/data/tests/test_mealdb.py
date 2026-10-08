import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_data import mealdb
from larder_db.models import Recipe

FIXTURE = Path(__file__).parent / "fixtures" / "meals.json"


@pytest.fixture
def meals() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text())["meals"]


def test_parse_meal(meals: list[dict[str, Any]]) -> None:
    draft = mealdb.parse_meal(meals[0])

    assert draft.source_id == "52772"
    assert draft.cuisine == "Japanese"
    assert draft.tags == ("meat", "casserole")
    assert draft.source_url is None
    assert [(i.position, i.name, i.measure) for i in draft.ingredients] == [
        (0, "soy sauce", "3/4 cup"),
        (1, "Chicken Breasts", "2"),
        (2, "Garlic", "1 clove"),
    ]


def test_parse_meal_falls_back_to_country(meals: list[dict[str, Any]]) -> None:
    draft = mealdb.parse_meal(meals[1])

    assert draft.cuisine == "Indian"
    assert draft.image_url is None
    assert draft.tags == ()


async def test_fetch_meals_dedupes_and_caches(tmp_path: Path) -> None:
    body = FIXTURE.read_text()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["f"])
        # Every letter returns the same two meals; they must be de-duplicated by id.
        return httpx.Response(
            200, text=body if request.url.params["f"] in "at" else '{"meals":null}'
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await mealdb.fetch_meals(client, tmp_path)
        second = await mealdb.fetch_meals(client, tmp_path)

    assert sorted(m["idMeal"] for m in first) == ["52772", "53000"]
    assert len(second) == 2
    assert len(calls) == 26  # second run is served from the cache


async def test_load_recipes_inserts_then_updates(
    db_session: AsyncSession, meals: list[dict[str, Any]]
) -> None:
    drafts = [mealdb.parse_meal(m) for m in meals]
    await mealdb.load_recipes(db_session, drafts)

    meals[0]["strMeal"] = "Renamed"
    meals[0]["strIngredient4"] = "Ginger"
    await mealdb.load_recipes(db_session, [mealdb.parse_meal(m) for m in meals])

    recipes = (
        await db_session.scalars(
            select(Recipe)
            .options(selectinload(Recipe.ingredients), selectinload(Recipe.tags))
            .order_by(Recipe.source_id)
        )
    ).all()
    assert [r.name for r in recipes] == ["Renamed", "Plain Rice"]
    assert [i.raw_name for i in recipes[0].ingredients] == [
        "soy sauce",
        "Chicken Breasts",
        "Ginger",
    ]
    assert sorted(t.tag for t in recipes[0].tags) == ["casserole", "meat"]
