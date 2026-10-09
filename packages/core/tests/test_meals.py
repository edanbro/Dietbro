from larder_core.meals import SLOT_ORDER, Slot, meal_types


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
