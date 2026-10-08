import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_data import embeddings, report, resolve
from larder_db.models import Food, FoodPortion, IngredientMatch, Recipe, RecipeIngredient

from .fakes import FakeEmbedder

# Real FDC ids so the curated alias table resolves "onion" and "olive oil".
ONION, OLIVE_OIL = 170000, 171413


@pytest.fixture
async def seeded(db_session: AsyncSession) -> AsyncSession:
    db_session.add_all(
        [
            Food(
                id=ONION,
                description="Onions, raw",
                data_type="sr_legacy",
                category="Vegetables and Vegetable Products",
                kcal=40,
                protein_g=1.1,
                fat_g=0.1,
                carbs_g=9.3,
                portions=[
                    FoodPortion(amount=1, unit="large", grams=150),
                    FoodPortion(amount=1, unit="medium", grams=110),
                ],
            ),
            Food(
                id=OLIVE_OIL,
                description="Oil, olive, salad or cooking",
                data_type="sr_legacy",
                category="Fats and Oils",
                kcal=884,
                protein_g=0,
                fat_g=100,
                carbs_g=0,
                portions=[FoodPortion(amount=1, unit="tbsp", grams=13.5)],
            ),
        ]
    )
    db_session.add_all(
        [
            Recipe(
                source="test",
                source_id="1",
                name="Fried onions",
                category="Side",
                ingredients=[
                    RecipeIngredient(position=0, raw_name="Onions", raw_measure="2 large"),
                    RecipeIngredient(position=1, raw_name="Olive Oil", raw_measure="2 tbsp"),
                ],
            ),
            Recipe(
                source="test",
                source_id="2",
                name="Mystery",
                ingredients=[
                    RecipeIngredient(position=0, raw_name="Onion", raw_measure="1"),
                    RecipeIngredient(position=1, raw_name="Unobtainium", raw_measure="pinch"),
                ],
            ),
        ]
    )
    await db_session.commit()
    await embeddings.embed_foods(db_session, FakeEmbedder())
    return db_session


async def test_resolve_all(seeded: AsyncSession) -> None:
    stats = await resolve.resolve_all(seeded, FakeEmbedder())

    assert stats.lines == 4
    assert stats.recipes_complete == 1
    lines = {
        i.raw_name: i
        for i in await seeded.scalars(select(RecipeIngredient).order_by(RecipeIngredient.id))
    }
    assert (lines["Onions"].food_id, lines["Onions"].grams) == (ONION, 300)
    assert lines["Onions"].match_method == "alias"
    assert lines["Olive Oil"].grams == pytest.approx(27)
    assert lines["Onion"].grams == 110
    assert lines["Unobtainium"].food_id is None

    recipes = {
        r.name: r
        for r in await seeded.scalars(select(Recipe).options(selectinload(Recipe.ingredients)))
    }
    fried = recipes["Fried onions"]
    assert fried.nutrition_complete
    total_kcal = 300 * 0.40 + 27 * 8.84
    assert fried.servings == 1  # ~359 kcal / 250 kcal side portion
    assert fried.kcal == pytest.approx(total_kcal)
    assert not recipes["Mystery"].nutrition_complete
    assert recipes["Mystery"].kcal is None

    cached = {m.name: m.method for m in await seeded.scalars(select(IngredientMatch))}
    assert cached == {"onion": "alias", "olive oil": "alias", "unobtainium": "unmatched"}


async def test_report(seeded: AsyncSession) -> None:
    await resolve.resolve_all(seeded, FakeEmbedder())

    r = await report.build_report(seeded)

    assert (r.lines, r.lines_with_food, r.lines_with_grams) == (4, 3, 3)
    assert r.food_coverage == 0.75
    assert (r.recipes, r.recipes_complete) == (2, 1)
    assert r.unmatched == [("unobtainium", 1)]
    assert "75.0%" in report.render(r)
