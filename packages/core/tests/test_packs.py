import pytest

from larder_core.packs import load_packs, pack_grams, packs_for


def test_the_table_loads() -> None:
    table = load_packs()
    assert table.fdc[171413] == 460  # olive oil, 500 ml
    assert table.category["Spices and Herbs"] == 40


@pytest.mark.parametrize(
    ("fdc_id", "description", "category", "expected"),
    [
        (171413, "Oil, olive, salad or cooking", "Fats and Oils", 460),  # exact food
        (1, "Tortillas, ready-to-bake or -fry, flour", "Baked Products", 320),  # keyword
        (2, "Spices, fennel seed", "Spices and Herbs", 40),  # category
        (3, "Soup, stock, fish, home-prepared", "Soups, Sauces, and Gravies", 500),
        (4, "Beef, ground, 90% lean meat / 10% fat, raw", "Beef Products", 500),
        (170000, "Onions, raw", "Vegetables and Vegetable Products", None),  # loose
        (5, "Peppers, sweet, yellow, raw", "Vegetables and Vegetable Products", None),
        (6, "Fish, haddock, raw", "Finfish and Shellfish Products", None),  # fish counter
        (7, "Something unlisted", None, None),
    ],
)
def test_pack_grams_by_food_keyword_then_category(
    fdc_id: int, description: str, category: str | None, expected: int | None
) -> None:
    assert pack_grams(fdc_id, description, category) == expected


def test_the_keyword_nearest_the_start_wins_over_the_category() -> None:
    assert pack_grams(9, "Milk, lowfat, fluid, 1% milkfat", "Dairy and Egg Products") == 1000
    # "canned" beats the vegetables' "loose" default; "egg" (first) beats "raw".
    assert pack_grams(9, "Tomatoes, red, ripe, canned", "Vegetables and Vegetable Products") == 400
    assert pack_grams(9, "Egg, duck, whole, fresh, raw", "Dairy and Egg Products") == 300


def test_packs_round_up_to_whole_packs() -> None:
    assert packs_for(15, 320) == 1
    assert packs_for(320, 320) == 1
    assert packs_for(321, 320) == 2
    assert packs_for(0.4, 40) == 1
