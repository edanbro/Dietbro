from datetime import date

import pytest

from larder_core.shelf_life import shelf_life_days, storage_for, suggest_expiry

BOUGHT = date(2026, 10, 12)


@pytest.mark.parametrize(
    ("description", "category", "days"),
    [
        ("Chicken, broilers or fryers, breast, meat only, raw", "Poultry Products", 2),
        ("Fish, salmon, Atlantic, farmed, raw", "Finfish and Shellfish Products", 2),
        ("Beef, ground, 85% lean meat / 15% fat, raw", "Beef Products", 3),
        ("Pork, fresh, loin, whole, separable lean only, raw", "Pork Products", 3),
        ("Ham, sliced, regular (approximately 11% fat)", "Sausages and Luncheon Meats", 5),
        ("Milk, whole, 3.25% milkfat, with added vitamin D", "Dairy and Egg Products", 7),
        ("Yogurt, Greek, plain, lowfat", "Dairy and Egg Products", 7),
        ("Cheese, cheddar", "Dairy and Egg Products", 21),
        ("Egg, whole, raw, fresh", "Dairy and Egg Products", 21),
        ("Butter, salted", "Dairy and Egg Products", 30),
        ("Spinach, raw", "Vegetables and Vegetable Products", 4),
        ("Broccoli, raw", "Vegetables and Vegetable Products", 5),
        ("Onions, raw", "Vegetables and Vegetable Products", 21),
        ("Potatoes, flesh and skin, raw", "Vegetables and Vegetable Products", 14),
        ("Strawberries, raw", "Fruits and Fruit Juices", 3),
        ("Bananas, raw", "Fruits and Fruit Juices", 5),
        ("Apples, raw, with skin", "Fruits and Fruit Juices", 21),
        ("Orange juice, chilled, includes from concentrate", "Fruits and Fruit Juices", 7),
        ("Bread, white, commercially prepared", "Baked Products", 4),
    ],
)
def test_fresh_food_keeps_days_by_category(description: str, category: str, days: int) -> None:
    assert shelf_life_days(description, category) == days


@pytest.mark.parametrize(
    ("description", "category"),
    [
        ("Peas, green, frozen, unprepared", "Vegetables and Vegetable Products"),
        (
            "Tomatoes, red, ripe, canned, packed in tomato juice",
            "Vegetables and Vegetable Products",
        ),
        ("Rice, white, long-grain, regular, raw, enriched", "Cereal Grains and Pasta"),
        ("Pasta, dry, enriched", "Cereal Grains and Pasta"),
        ("Beans, baked, canned, plain or vegetarian", "Legumes and Legume Products"),
        ("Oil, olive, salad or cooking", "Fats and Oils"),
        ("Crackers, saltines", "Baked Products"),
        ("Honey", "Sweets"),
        ("Something", None),
    ],
)
def test_shelf_stable_food_has_no_suggested_date(description: str, category: str | None) -> None:
    assert shelf_life_days(description, category) is None


def test_suggest_expiry_counts_from_purchase() -> None:
    assert suggest_expiry(BOUGHT, "Broccoli, raw", "Vegetables and Vegetable Products") == date(
        2026, 10, 17
    )
    assert suggest_expiry(BOUGHT, "Honey", "Sweets") is None


def test_storage_on_the_receipt_wins() -> None:
    chicken = ("Chicken, broilers or fryers, breast, meat only, raw", "Poultry Products")

    assert suggest_expiry(BOUGHT, *chicken, storage="frozen") is None
    assert suggest_expiry(BOUGHT, "Broccoli, raw", "Vegetables", storage="ambient") is None
    assert suggest_expiry(BOUGHT, *chicken) == date(2026, 10, 14)


@pytest.mark.parametrize(
    ("description", "category", "place"),
    [
        ("Chicken, broilers or fryers, breast, raw", "Poultry Products", "fridge"),
        ("Milk, whole, 3.25% milkfat", "Dairy and Egg Products", "fridge"),
        ("Milk, dry, whole", "Dairy and Egg Products", "cupboard"),
        ("Peas, green, frozen, unprepared", "Vegetables and Vegetable Products", "freezer"),
        ("Spinach, raw", "Vegetables and Vegetable Products", "fridge"),
        ("Potatoes, flesh and skin, raw", "Vegetables and Vegetable Products", "cupboard"),
        ("Onions, raw", "Vegetables and Vegetable Products", "cupboard"),
        ("Strawberries, raw", "Fruits and Fruit Juices", "fridge"),
        ("Bananas, raw", "Fruits and Fruit Juices", "cupboard"),
        ("Beans, baked, canned", "Legumes and Legume Products", "cupboard"),
        ("Bread, white", "Baked Products", "cupboard"),
        ("Mystery food", None, "cupboard"),
    ],
)
def test_storage_for(description: str, category: str | None, place: str) -> None:
    assert storage_for(description, category) == place
