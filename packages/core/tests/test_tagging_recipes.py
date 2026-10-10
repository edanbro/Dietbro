"""Golden recipes: rows copied from the real catalog (TheMealDB recipes as resolved in the local
database: name, category, an excerpt of the instructions with every sentence that mentions a
tagged food, and every ingredient line with its matched USDA food). Runs in CI without a database.

The excerpts keep the sentences that carry tags, so the instructions backstop is exercised:
Lamb Tagine's pine nuts and the Smoky Lentil Chili's Worcestershire sauce appear only there.
"""

import json
from pathlib import Path
from typing import TypedDict, cast

import pytest

from larder_core.tagging import Diet, make_line, recipe_tags, tag_food


class FixtureLine(TypedDict):
    raw_name: str
    raw_measure: str
    food_id: int | None
    description: str | None
    category: str | None
    match_method: str | None


class FixtureRecipe(TypedDict):
    name: str
    category: str | None
    source_id: str
    instructions_excerpt: str
    lines: list[FixtureLine]
    expect: list[str]
    never: list[str]


FIXTURE = cast(
    list[FixtureRecipe],
    json.loads((Path(__file__).parent / "data" / "golden_recipes.json").read_text("utf-8")),
)


def _tags(recipe: FixtureRecipe) -> tuple[set[str], int, list[Diet]]:
    lines = [
        make_line(
            line["raw_name"],
            line["food_id"],
            tag_food(line["food_id"], line["description"] or "", line["category"])
            if line["food_id"] is not None
            else None,
        )
        for line in recipe["lines"]
    ]
    r = recipe_tags(recipe["name"], recipe["category"], recipe["instructions_excerpt"], lines)
    return {str(t) for t in r.allergens | r.animal}, r.unresolved, r.suitable_for()


def test_fixture_covers_the_spec_recipes() -> None:
    names = {r["name"] for r in FIXTURE}
    assert len(names) == len(FIXTURE) >= 15
    assert {"Egg Drop Soup", "Sushi", "Frog Legs Recipe in Garlic Butter", "Chelsea Buns"} <= names


@pytest.mark.parametrize("recipe", FIXTURE, ids=[r["name"] for r in FIXTURE])
def test_golden_recipe(recipe: FixtureRecipe) -> None:
    found, unresolved, diets = _tags(recipe)
    assert set(recipe["expect"]) <= found, f"missing {set(recipe['expect']) - found}"
    assert not set(recipe["never"]) & found, f"unexpected {set(recipe['never']) & found}"
    # Every line is an exact alias or has a reviewed line_tags row.
    assert unresolved == 0
    if "meat" in found:
        assert diets == []


def test_frog_legs_are_meat_not_fish() -> None:
    (frog,) = [r for r in FIXTURE if r["name"].startswith("Frog Legs")]
    found, _, diets = _tags(frog)
    assert "meat" in found
    assert "fish" not in found
    assert Diet.PESCATARIAN not in diets


def test_vegetarian_category_is_not_a_diet_claim() -> None:
    # Egg Drop Soup is filed under "Vegetarian" in TheMealDB but is made with chicken broth.
    (soup,) = [r for r in FIXTURE if r["name"] == "Egg Drop Soup"]
    assert soup["category"] == "Vegetarian"
    found, _, diets = _tags(soup)
    assert "meat" in found
    assert diets == []
