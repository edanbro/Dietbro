import pytest

from larder_core.meals import (
    SLOT_ORDER,
    SNACK_SHARE,
    SNACK_SLOTS,
    Slot,
    day_shares,
    default_mode,
    everyday_slots,
    load_everyday,
    load_overrides,
    meal_types,
    own_shares,
    recipe_slots,
)


def test_slot_order_is_eating_order() -> None:
    assert SLOT_ORDER == (
        Slot.BREAKFAST,
        Slot.MORNING_SNACK,
        Slot.LUNCH,
        Slot.SNACK,
        Slot.DINNER,
        Slot.EVENING_SNACK,
    )


def test_mains_fill_lunch_and_dinner() -> None:
    assert meal_types("Chicken") == {Slot.LUNCH, Slot.DINNER}
    assert meal_types("Breakfast") == {Slot.BREAKFAST}
    assert meal_types("Snack") == SNACK_SLOTS


def test_sides_and_unknown_categories_are_never_planned_alone() -> None:
    assert meal_types("Side") == frozenset()
    assert meal_types(None) == frozenset()
    assert meal_types("Something new") == frozenset()


def test_recipe_slots_by_category_when_nutrition_is_plausible() -> None:
    assert recipe_slots("mealdb", "x", "Chicken", 650, 0.05) == {Slot.LUNCH, Slot.DINNER}


def test_recipe_slots_excludes_implausible_nutrition() -> None:
    assert recipe_slots("mealdb", "x", "Chicken", 1439, 0.05) == frozenset()  # fried chicken
    assert recipe_slots("mealdb", "x", "Chicken", 650, 0.4) == frozenset()  # frying oil
    assert recipe_slots("mealdb", "x", "Chicken", None, 0.0) == frozenset()
    assert recipe_slots("mealdb", "x", "Chicken", 650, 0.0, 2569) == frozenset()  # a pot's salt
    assert recipe_slots("mealdb", "x", "Chicken", 650, 0.0, 900) == {Slot.LUNCH, Slot.DINNER}


def test_overrides_parse_and_reference_valid_slots() -> None:
    for (source, source_id), o in load_overrides().items():
        assert (o.source, o.source_id) == (source, source_id)
        assert o.note, f"override {source}/{source_id} needs a note"
        assert recipe_slots(source, source_id, "Chicken", 650, 0.0) == o.slots


def test_a_catalogue_recipe_must_be_big_enough_to_be_a_meal() -> None:
    mains = {Slot.LUNCH, Slot.DINNER}
    assert recipe_slots("mealdb", "x", "Vegetarian", 219, 0.0) == frozenset()  # padron peppers
    assert recipe_slots("mealdb", "x", "Vegetarian", 300, 0.0, 100, 5) == frozenset()  # all veg
    assert recipe_slots("mealdb", "x", "Vegetarian", 300, 0.0, 100, 12) == mains
    assert recipe_slots("mealdb", "x", "Breakfast", 144, 0.0) == frozenset()  # grits alone
    assert recipe_slots("mealdb", "x", "Dessert", 420, 0.0) == frozenset()  # a slice of a big bake
    assert recipe_slots("curated", "x", "Snack", 110, 0.0) == SNACK_SLOTS  # snacks can be small


def test_a_users_own_recipe_keeps_its_slots_however_small() -> None:
    mains = {Slot.LUNCH, Slot.DINNER}
    assert recipe_slots("imported", "x", "Miscellaneous", 150, 0.0, 100, 3) == mains


def test_roasted_peanuts_are_a_snack() -> None:
    # What started all this: filed as a starter, so planned as a whole lunch.
    assert recipe_slots("mealdb", "53429", "Starter", 410, 0.1, 100, 16) == SNACK_SLOTS


def test_everyday_slots() -> None:
    mains = frozenset({Slot.LUNCH, Slot.DINNER})
    # A listed recipe gets the slots listed, a curated main is a dinner, and anything else from
    # TheMealDB is no everyday meal.
    assert everyday_slots("mealdb", "52770", mains) == {Slot.DINNER}
    assert everyday_slots("mealdb", "53367", mains) == mains
    assert everyday_slots("mealdb", "53029", mains) == frozenset()
    assert everyday_slots("curated", "irish-stew", mains) == {Slot.DINNER}
    assert everyday_slots("curated", "ham-cheese-salad-sandwich", frozenset({Slot.LUNCH})) == {
        Slot.LUNCH
    }
    assert everyday_slots("curated", "besan-pancakes", frozenset({Slot.BREAKFAST})) == frozenset()
    # Never a slot the recipe can't fill.
    assert everyday_slots("mealdb", "52770", frozenset({Slot.LUNCH})) == frozenset()


def test_the_everyday_list_parses() -> None:
    rows = load_everyday()
    assert len(rows) > 100
    assert all(source in {"mealdb", "curated"} for source, _ in rows)


def test_day_shares_are_of_the_meals_eaten() -> None:
    modes = {Slot.BREAKFAST: "plan", Slot.LUNCH: "plan", Slot.DINNER: "plan", Slot.SNACK: "skip"}
    assert day_shares(modes) == {Slot.BREAKFAST: 0.25, Slot.LUNCH: 0.35, Slot.DINNER: 0.40}
    shares = day_shares(modes | {Slot.BREAKFAST: "skip", Slot.LUNCH: "own"})
    assert shares == pytest.approx({Slot.DINNER: 0.40 / 0.75})


def test_snacks_leave_the_meals_a_little_less_of_the_day() -> None:
    modes = {Slot.BREAKFAST: "plan", Slot.LUNCH: "plan", Slot.DINNER: "plan", Slot.SNACK: "plan"}
    assert day_shares(modes)[Slot.DINNER] == pytest.approx(0.36)
    all_three = modes | {Slot.MORNING_SNACK: "plan", Slot.EVENING_SNACK: "own"}
    assert day_shares(all_three)[Slot.DINNER] == pytest.approx(0.28)


def test_an_own_snack_keeps_its_share_free() -> None:
    modes = {Slot.BREAKFAST: "plan", Slot.LUNCH: "plan", Slot.DINNER: "plan"}
    assert own_shares(modes | {Slot.EVENING_SNACK: "own"}) == {Slot.EVENING_SNACK: SNACK_SHARE}
    assert own_shares(modes | {Slot.EVENING_SNACK: "plan"}) == {}


def test_one_snack_a_day_unless_the_user_says_otherwise() -> None:
    assert default_mode(Slot.SNACK) == "plan"
    assert default_mode(Slot.MORNING_SNACK) == default_mode(Slot.EVENING_SNACK) == "skip"
    assert default_mode(Slot.LUNCH) == "plan"
