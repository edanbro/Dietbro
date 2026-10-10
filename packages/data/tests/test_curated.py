import csv
from pathlib import Path
from typing import Any

import pytest

from larder_core.aliases import load_aliases
from larder_core.allergens import Allergen
from larder_core.names import normalise_name
from larder_core.tagging import (
    Diet,
    FoodTags,
    Line,
    RecipeTags,
    diet_allows,
    make_line,
    recipe_tags,
    tag_food,
)
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


# --- the shipped recipes ----------------------------------------------------------------------

SNAPSHOT = Path(__file__).parents[2] / "core" / "tests" / "data" / "food_tags_snapshot.csv"


def _foods() -> dict[int, FoodTags]:
    with SNAPSHOT.open(encoding="utf-8") as f:
        return {
            int(r["fdc_id"]): tag_food(int(r["fdc_id"]), r["description"], r["category"] or None)
            for r in csv.DictReader(f)
        }


def _tags() -> dict[str, tuple[str, RecipeTags]]:
    aliases = load_aliases()
    foods = _foods()
    out: dict[str, tuple[str, RecipeTags]] = {}
    for d in curated.load():
        lines: list[Line] = []
        for i in d.ingredients:
            fid = aliases[normalise_name(i.name)]
            lines.append(make_line(i.name, fid, foods[fid]))
        out[d.source_id] = (
            d.category or "",
            recipe_tags(d.name, d.category, d.instructions, lines),
        )
    return out


def test_every_ingredient_is_an_exact_curated_alias() -> None:
    """Seeding works without the embedding model, and no line needs a tag review."""
    aliases = load_aliases()
    for d in curated.load():
        for i in d.ingredients:
            assert normalise_name(i.name) in aliases, f"{d.source_id}: {i.name!r} has no alias"
    for slug, (_, tags) in _tags().items():
        assert tags.complete, f"{slug}: a line is approximate or unreviewed"


PROFILES: list[tuple[frozenset[Allergen], Diet | None]] = [
    (frozenset(), None),
    *[(frozenset({a}), None) for a in Allergen],
    (frozenset(), Diet.VEGETARIAN),
    (frozenset(), Diet.VEGAN),
    (frozenset(), Diet.PESCATARIAN),
    (frozenset({Allergen.GLUTEN}), Diet.VEGAN),
    (frozenset({Allergen.SOY}), Diet.VEGAN),
    (frozenset({Allergen.MILK, Allergen.EGGS}), None),
    (frozenset({Allergen.MILK, Allergen.EGGS, Allergen.GLUTEN}), None),
    (frozenset({Allergen.GLUTEN, Allergen.MILK}), None),
    (frozenset({Allergen.TREE_NUTS, Allergen.PEANUTS}), None),
]


@pytest.mark.parametrize(("allergens", "diet"), PROFILES)
def test_common_restrictions_still_fill_a_week(
    allergens: frozenset[Allergen], diet: Diet | None
) -> None:
    """Breakfasts may repeat 4x a week, so >= 2 would do; we want real choice (docs/adr/0010)."""
    allowed = {
        slug: category
        for slug, (category, tags) in _tags().items()
        if not (tags.allergens & allergens) and diet_allows(diet, tags.animal)
    }
    breakfasts = sum(c == "Breakfast" for c in allowed.values())
    snacks = sum(c == "Snack" for c in allowed.values())
    assert breakfasts >= 6, f"only {breakfasts} breakfasts for {sorted(allergens)} {diet}"
    assert snacks >= 3, f"only {snacks} snacks for {sorted(allergens)} {diet}"
