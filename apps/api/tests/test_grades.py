"""Nutrition grades (Nutri-Score method) for foods and recipes."""

from larder_api.routers.foods import food_grade
from larder_api.routers.recipes import recipe_grade
from larder_db.models import Food, Recipe, RecipeIngredient

BUTTER = Food(
    id=1,
    source="usda",
    description="Butter, salted",
    category="Dairy and Egg Products",
    kcal=717,
    protein_g=0.9,
    sat_fat_g=51,
    sugars_g=0.1,
    sodium_mg=643,
    fiber_g=0,
)
APPLE = Food(
    id=2,
    source="usda",
    description="Apples, raw, with skin",
    category="Fruits and Fruit Juices",
    kcal=52,
    protein_g=0.3,
    sat_fat_g=0,
    sugars_g=10,
    sodium_mg=1,
    fiber_g=2.4,
)


def test_food_grades() -> None:
    assert food_grade(BUTTER) == "E"
    assert food_grade(APPLE) == "A"


def test_a_products_own_grade_wins() -> None:
    product = Food(id=3, source="off", description="Butter", off_grade="c", kcal=717)
    assert food_grade(product) == "C"


def test_unknown_nutrients_give_no_grade() -> None:
    assert food_grade(Food(id=4, source="usda", description="Mystery")) is None


def _stewed_apples(complete: bool = True) -> Recipe:
    recipe = Recipe(
        id=1,
        source="curated",
        source_id="x",
        name="Stewed apples",
        servings=2,
        nutrition_complete=complete,
        # per serving, of 2 x 200 g
        kcal=104,
        protein_g=0.6,
        sat_fat_g=0,
        sugars_g=20,
        sodium_mg=2,
        fiber_g=4.8,
    )
    recipe.ingredients = [
        RecipeIngredient(position=0, raw_name="apples", food_id=APPLE.id, grams=400)
    ]
    return recipe


def test_recipe_grade_is_per_100g_of_the_dish() -> None:
    assert recipe_grade(_stewed_apples(), {APPLE.id: APPLE}) == "A"


def test_incomplete_recipes_get_no_grade() -> None:
    assert recipe_grade(_stewed_apples(complete=False), {APPLE.id: APPLE}) is None
