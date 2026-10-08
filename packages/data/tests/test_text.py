import pytest
from hypothesis import given
from hypothesis import strategies as st

from larder_data.text import normalise_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Onion", "onion"),
        ("Onions", "onion"),
        ("  Red  Onions ", "red onion"),
        ("Potatoes", "potato"),
        ("Tomatoes", "tomato"),
        ("Bay Leaves", "bay leaf"),
        ("Raspberries", "raspberry"),
        ("Red Chillies", "red chilli"),
        ("Peaches", "peach"),
        ("Eggs", "egg"),
        ("Chickpeas", "chickpea"),
        ("Fresh Basil", "basil"),
        ("Freshly Chopped Parsley", "parsley"),
        ("Large Free-range Eggs", "egg"),
        ("Boneless Skinless Chicken Breasts", "chicken breast"),
        ("Extra Virgin Olive Oil", "extra virgin olive oil"),
        ("Ground Cumin", "ground cumin"),
        ("Plain flour", "plain flour"),
        ("Asparagus", "asparagus"),
        ("Couscous", "couscous"),
        ("Hummus", "hummus"),
        ("Molasses", "molasses"),
        ("Swiss cheese", "swiss cheese"),
        ("Brussels Sprouts", "brussels sprout"),
        ("Jalapeño", "jalapeno"),
        ("Crème fraîche", "creme fraiche"),
        ("Self-raising Flour", "self-raising flour"),
        ("Tomato Puree", "tomato puree"),
        ("Garlic Clove", "garlic clove"),
        ("Lemon (juice)", "lemon juice"),
        ("Gruyère", "gruyere"),
        ("Pappardelle pasta", "pappardelle pasta"),
        ("Hass Avocado", "hass avocado"),
        ("Eggs, beaten", "egg"),
        ("Melted Butter", "butter"),
        ("Can of Chickpeas", "chickpea"),
        ("tin of tomatoes", "tomato"),
    ],
)
def test_normalise_name(raw: str, expected: str) -> None:
    assert normalise_name(raw) == expected


@given(st.text(max_size=40))
def test_normalise_is_idempotent(raw: str) -> None:
    once = normalise_name(raw)
    assert normalise_name(once) == once
