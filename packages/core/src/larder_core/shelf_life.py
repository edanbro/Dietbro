"""Suggested use-by dates for food bought today (receipt intake, docs/adr/0016).

A small, conservative table: days a fresh food keeps in the fridge or cupboard after purchase,
by USDA category, with keyword overrides for foods that keep much longer or shorter than their
category (onions and apples for weeks, berries and salad leaves for days). Frozen, canned and
dry foods get no date: the user can add one. The receipt's own storage hint (FROZEN, a tin)
wins over the matched food, which is often the fresh one.

| Food | Days | Food | Days |
|---|---|---|---|
| Poultry, fish and shellfish | 2 | Beef, pork, lamb, game | 3 |
| Sausages, ham, cooked meats | 5 | Milk, cream, yogurt (dairy default) | 7 |
| Hard cheese, eggs | 21 | Butter | 30 |
| Vegetables (default) | 5 | Salad leaves, spinach | 4 |
| Potatoes, carrots, cabbage | 14 | Onions | 21 |
| Garlic | 30 | Fruit (default), bananas | 5 |
| Berries | 3 | Citrus | 14 |
| Apples | 21 | Juice | 7 |
| Bread | 4 | Everything else | none |

Sources: rounded down from FoodKeeper (USDA FSIS) refrigerator times and UK supermarket
"use by"/"best before" norms; a suggestion the user confirms on the review screen, not advice.
"""

from datetime import date, timedelta
from typing import Literal

type Storage = Literal["frozen", "ambient"]

# Description words meaning the food keeps for months.
_SHELF_STABLE = ("frozen", "canned", "dried", "dry", "dehydrated", "powder", "uht", "jarred")

_CATEGORY_DAYS: dict[str, int] = {
    "Poultry Products": 2,
    "Finfish and Shellfish Products": 2,
    "Beef Products": 3,
    "Pork Products": 3,
    "Lamb, Veal, and Game Products": 3,
    "Sausages and Luncheon Meats": 5,
    "Dairy and Egg Products": 7,
    "Vegetables and Vegetable Products": 5,
    "Fruits and Fruit Juices": 5,
}
# (category, first word(s) of the USDA description) -> days; checked before the category.
_OVERRIDES: list[tuple[str, tuple[str, ...], int]] = [
    ("Dairy and Egg Products", ("cheese, cottage", "cheese, ricotta", "cheese, cream"), 7),
    ("Dairy and Egg Products", ("cheese", "egg"), 21),
    ("Dairy and Egg Products", ("butter",), 30),
    ("Vegetables and Vegetable Products", ("spinach", "lettuce", "arugula", "cress"), 4),
    (
        "Vegetables and Vegetable Products",
        ("potato", "sweet potato", "carrot", "cabbage", "squash", "beets", "turnip", "parsnip"),
        14,
    ),
    ("Vegetables and Vegetable Products", ("onion",), 21),
    ("Vegetables and Vegetable Products", ("garlic",), 30),
    ("Fruits and Fruit Juices", ("strawberr", "raspberr", "blueberr", "blackberr"), 3),
    ("Fruits and Fruit Juices", ("orange juice", "apple juice", "grape juice"), 7),
    ("Fruits and Fruit Juices", ("orange", "lemon", "lime", "grapefruit", "tangerine"), 14),
    ("Fruits and Fruit Juices", ("apple",), 21),
    ("Baked Products", ("bread", "rolls", "english muffin", "bagel"), 4),
]


def shelf_life_days(description: str, category: str | None) -> int | None:
    """Days the food keeps after purchase, or None for shelf-stable or unknown food."""
    text = description.lower()
    words = set(text.replace(",", " ").split())
    if any(w in words for w in _SHELF_STABLE):
        return None
    for cat, prefixes, days in _OVERRIDES:
        if cat == category and text.startswith(prefixes):
            return days
    if category == "Fruits and Fruit Juices" and "juice" in words:
        return 7
    return _CATEGORY_DAYS.get(category or "")


def suggest_expiry(
    purchased_on: date,
    description: str,
    category: str | None,
    *,
    storage: Storage | None = None,
) -> date | None:
    """Suggested use-by date: purchase date + shelf life; none when the receipt says frozen or
    tinned, or the food keeps for months."""
    if storage is not None:
        return None
    days = shelf_life_days(description, category)
    return None if days is None else purchased_on + timedelta(days=days)


type Place = Literal["fridge", "freezer", "cupboard"]

_CHILLED = frozenset(
    {
        "Poultry Products",
        "Finfish and Shellfish Products",
        "Beef Products",
        "Pork Products",
        "Lamb, Veal, and Game Products",
        "Sausages and Luncheon Meats",
        "Dairy and Egg Products",
    }
)
# Vegetables kept out of the fridge; fruit kept in it (the rest live in a bowl).
_CUPBOARD_VEG = ("potato", "sweet potato", "onion", "garlic", "squash", "pumpkin", "yam")
_FRIDGE_FRUIT = ("strawberr", "raspberr", "blueberr", "blackberr", "grape", "cherr", "melon")


def storage_for(description: str, category: str | None) -> Place:
    """Where a food is usually kept, for grouping the pantry list: frozen food in the freezer,
    fresh meat, fish, dairy, most vegetables and soft fruit in the fridge, the rest (tins, dry
    goods, bread, potatoes and onions, a fruit bowl) in the cupboard. A guess for display."""
    text = description.lower()
    words = set(text.replace(",", " ").split())
    if "frozen" in words:
        return "freezer"
    if any(w in words for w in _SHELF_STABLE):
        return "cupboard"
    if category in _CHILLED:
        return "fridge"
    if category == "Vegetables and Vegetable Products":
        return "cupboard" if text.startswith(_CUPBOARD_VEG) else "fridge"
    if category == "Fruits and Fruit Juices":
        return "fridge" if text.startswith(_FRIDGE_FRUIT) or "juice" in words else "cupboard"
    return "cupboard"
