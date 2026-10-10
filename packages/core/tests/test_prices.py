import pytest

from larder_core.prices import (
    DEFAULT_PRICE,
    MAX_PENCE_PER_KG,
    Price,
    convert,
    load_prices,
    price,
)

# Every food category in USDA FoodData Central SR Legacy (the categories in the foods table).
USDA_CATEGORIES = (
    "American Indian/Alaska Native Foods",
    "Baby Foods",
    "Baked Products",
    "Beef Products",
    "Beverages",
    "Breakfast Cereals",
    "Cereal Grains and Pasta",
    "Dairy and Egg Products",
    "Fast Foods",
    "Fats and Oils",
    "Finfish and Shellfish Products",
    "Fruits and Fruit Juices",
    "Lamb, Veal, and Game Products",
    "Legumes and Legume Products",
    "Meals, Entrees, and Side Dishes",
    "Nut and Seed Products",
    "Pork Products",
    "Poultry Products",
    "Restaurant Foods",
    "Sausages and Luncheon Meats",
    "Snacks",
    "Soups, Sauces, and Gravies",
    "Spices and Herbs",
    "Sweets",
    "Vegetables and Vegetable Products",
)


def test_every_category_has_a_default() -> None:
    assert set(USDA_CATEGORIES) <= load_prices().category.keys()


def test_prices_are_in_range() -> None:
    table = load_prices()
    every = [*table.fdc.values(), *(p for _, p in table.keywords), *table.category.values()]
    assert len(table.fdc) + len(table.keywords) >= 150
    assert all(0 <= p.pence_per_kg <= MAX_PENCE_PER_KG for p in every)
    # Only tap water and ice are free, and nothing free is shopped for.
    assert all(p.shop == (p.pence_per_kg > 0) for p in every)


def test_tap_water_and_ice_are_never_bought() -> None:
    assert price(173647, "Beverages, water, tap, drinking", "Beverages") == Price(0, shop=False)
    assert price(1, "Beverages, water, tap, municipal", "Beverages") == Price(0, shop=False)
    assert price(2, "Ice cubes", None) == Price(0, shop=False)
    # Bottled water and coconut water are not tap water.
    assert price(3, "Water, bottled, generic", "Beverages").shop
    assert price(4, "Beverages, coconut water, ready-to-drink", "Beverages").shop


def test_lookup_order() -> None:
    # fdc override beats the keyword rule for the same description.
    assert price(171413, "Oil, olive, salad or cooking", "Fats and Oils").pence_per_kg == 850
    assert price(9, "Oil, olive, extra virgin", "Fats and Oils").pence_per_kg == 850
    assert price(9, "Oil, rapeseed", "Fats and Oils").pence_per_kg == 250  # keyword "oil"
    # No keyword: category default; unknown category: global default.
    assert price(9, "Quorn pieces", "Meals, Entrees, and Side Dishes").pence_per_kg == 700
    assert price(9, "Quorn pieces", None) == DEFAULT_PRICE
    assert price(9, "Quorn pieces", "Something new") == DEFAULT_PRICE


@pytest.mark.parametrize(
    ("description", "category", "pence"),
    [
        # Most words wins at the same position.
        ("Cheese, parmesan, grated", "Dairy and Egg Products", 2000),
        ("Cheese, edam", "Dairy and Egg Products", 1000),
        ("Spices, pepper, black", "Spices and Herbs", 2000),
        ("Spices, saffron", "Spices and Herbs", 600_000),
        # The match nearest the start wins: USDA names lead with the food.
        ("Cookies, chocolate sandwich, with creme filling", "Baked Products", 600),
        ("Candies, milk chocolate", "Sweets", 1000),
        ("Pepper, banana, raw", "Vegetables and Vegetable Products", 500),
        # Singular and plural, accents and case don't matter; whole words only.
        ("ONIONS, RAW", None, 90),
        ("Crème fraîche", "Dairy and Egg Products", 450),
        ("Saltines", "Baked Products", 450),
        ("Butternut squash", "Vegetables and Vegetable Products", 250),
    ],
)
def test_keywords(description: str, category: str | None, pence: int) -> None:
    assert price(999_999_999, description, category).pence_per_kg == pence


def test_staples_are_cheap_and_spices_dear() -> None:
    def pence(fdc_id: int, description: str, category: str) -> int:
        return price(fdc_id, description, category).pence_per_kg

    assert pence(173468, "Salt, table", "Spices and Herbs") <= 100
    assert pence(169655, "Sugars, granulated", "Sweets") <= 150
    assert pence(168936, "Wheat flour, white, all-purpose", "Cereal Grains and Pasta") <= 120
    assert 1000 <= pence(171320, "Spices, cinnamon, ground", "Spices and Herbs") <= 5000
    assert pence(170848, "Cheese, parmesan, hard", "Dairy and Egg Products") > pence(
        328637, "Cheese, cheddar", "Dairy and Egg Products"
    )


def test_convert() -> None:
    assert convert(1000, "GBP") == 1000
    assert convert(1000, "EUR") == 1170
    assert convert(1000, "USD") == 1270
    assert convert(0, "EUR") == 0
