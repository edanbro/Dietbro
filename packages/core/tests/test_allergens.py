from larder_core.allergens import LABELS, Allergen


def test_every_allergen_has_a_label() -> None:
    assert set(LABELS) == set(Allergen)
    assert len(Allergen) == 14
