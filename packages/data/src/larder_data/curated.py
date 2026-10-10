"""Curated breakfasts and snacks (curated.toml): simple recipes built from USDA foods that fill
the gaps in TheMealDB (docs/adr/0010-meal-slots-and-curated-recipes.md).

Every ingredient name is a curated alias, so these resolve without the embedding model, and
serving counts are explicit rather than estimated.
"""

import tomllib
from importlib import resources
from typing import Any

from larder_data.mealdb import IngredientLine, RecipeDraft

SOURCE = "curated"
CATEGORIES = frozenset({"Breakfast", "Snack"})


def parse(data: dict[str, Any]) -> list[RecipeDraft]:
    drafts: list[RecipeDraft] = []
    seen: set[str] = set()
    for r in data.get("recipe", []):
        slug = str(r["slug"])
        if slug in seen:
            raise ValueError(f"duplicate curated recipe slug: {slug}")
        seen.add(slug)
        if r["category"] not in CATEGORIES:
            raise ValueError(f"{slug}: category must be one of {sorted(CATEGORIES)}")
        servings = int(r["servings"])
        if servings < 1:
            raise ValueError(f"{slug}: servings must be >= 1")
        lines = tuple(
            IngredientLine(i, str(name), str(measure))
            for i, (name, measure) in enumerate(r["ingredients"])
        )
        if not lines:
            raise ValueError(f"{slug}: no ingredients")
        drafts.append(
            RecipeDraft(
                source_id=slug,
                name=str(r["name"]),
                category=str(r["category"]),
                cuisine=r.get("cuisine"),
                instructions=str(r["instructions"]).strip(),
                image_url=None,
                source_url=None,
                tags=tuple(r.get("tags", ())),
                ingredients=lines,
                servings=servings,
            )
        )
    return drafts


def load() -> list[RecipeDraft]:
    path = resources.files("larder_data") / "curated.toml"
    with path.open("rb") as f:
        return parse(tomllib.load(f))
