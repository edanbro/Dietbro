"""Curated ingredient vocabulary: normalised name -> USDA FoodData Central id.

`data/aliases.csv` is hand-reviewed (docs/adr/0006-ingredient-matching.md). Rows marked
`approximation` map to the nearest nutritional stand-in rather than the same food.
"""

import csv
from dataclasses import dataclass
from functools import cache
from importlib import resources


@dataclass(frozen=True, slots=True)
class Alias:
    name: str
    fdc_id: int
    description: str
    approximation: bool  # nearest nutritional stand-in, not the same food


@cache
def load_alias_rows() -> tuple[Alias, ...]:
    """Curated table (resources/aliases.csv): normalised name -> FDC food, hand-reviewed."""
    path = resources.files("larder_core") / "data" / "aliases.csv"
    with path.open(encoding="utf-8") as f:
        return tuple(
            Alias(r["name"], int(r["fdc_id"]), r["description"], r["note"].startswith("approx"))
            for r in csv.DictReader(f)
        )


def load_aliases() -> dict[str, int]:
    return {a.name: a.fdc_id for a in load_alias_rows()}
