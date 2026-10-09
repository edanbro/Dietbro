from typing import Any

import pytest

from larder_data import curated


def recipe(**overrides: Any) -> dict[str, Any]:
    return {
        "slug": "porridge",
        "name": "Porridge",
        "category": "Breakfast",
        "servings": 1,
        "instructions": "Simmer.\n",
        "ingredients": [["rolled oats", "50g"], ["milk", "250ml"]],
    } | overrides


def test_parse_builds_drafts_with_explicit_servings() -> None:
    [draft] = curated.parse({"recipe": [recipe(tags=["vegetarian"])]})

    assert (draft.source_id, draft.category, draft.servings) == ("porridge", "Breakfast", 1)
    assert [(i.position, i.name, i.measure) for i in draft.ingredients] == [
        (0, "rolled oats", "50g"),
        (1, "milk", "250ml"),
    ]
    assert draft.instructions == "Simmer."
    assert draft.tags == ("vegetarian",)


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ({"recipe": [recipe(), recipe()]}, "duplicate"),
        ({"recipe": [recipe(category="Dessert")]}, "category"),
        ({"recipe": [recipe(servings=0)]}, "servings"),
        ({"recipe": [recipe(ingredients=[])]}, "no ingredients"),
    ],
)
def test_parse_rejects_bad_rows(data: dict[str, Any], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        curated.parse(data)
