from larder_core.meals import SLOT_ORDER, Slot, load_overrides, meal_types, recipe_slots


def test_slot_order_is_eating_order() -> None:
    assert SLOT_ORDER == (Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER, Slot.SNACK)


def test_mains_fill_lunch_and_dinner() -> None:
    assert meal_types("Chicken") == {Slot.LUNCH, Slot.DINNER}
    assert meal_types("Breakfast") == {Slot.BREAKFAST}
    assert meal_types("Snack") == {Slot.SNACK}


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


def test_overrides_parse_and_reference_valid_slots() -> None:
    for (source, source_id), o in load_overrides().items():
        assert (o.source, o.source_id) == (source, source_id)
        assert o.note, f"override {source}/{source_id} needs a note"
        assert recipe_slots(source, source_id, "Chicken", 650, 0.0) == o.slots
