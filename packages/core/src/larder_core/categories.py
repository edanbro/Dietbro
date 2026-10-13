"""Other sources' food categories mapped to USDA category names (`foods.category`), so tagging,
prices, shelf life and shopping aisles work for every food. Reviewed tables in data/:

- wweia_categories.csv: USDA survey foods (FNDDS) WWEIA category code -> category. Every code
  must be listed; a blank category (with a note) means "no category rules".
- cofid_groups.csv: UK CoFID food group code -> category, longest prefix wins ("MAA" bacon
  before "M" meat dishes). A group no prefix covers is an error.
- off_categories.csv: Open Food Facts category tag -> category. Products list tags general to
  specific; the most specific mapped one wins, and none is fine (crowdsourced, open-ended).

Where a group straddles categories the safer one is chosen (butter is dairy, so it keeps the
milk tag); see each row's note.
"""

import csv
from collections.abc import Iterable
from functools import cache
from importlib import resources

from larder_core.prices import load_prices

__all__ = [
    "UnmappedCategory",
    "cofid_category",
    "known_categories",
    "off_category",
    "wweia_category",
]


class UnmappedCategory(KeyError):
    """A WWEIA code or CoFID group missing from the reviewed tables: review it, don't guess."""


def known_categories() -> frozenset[str]:
    """The USDA category names the price table covers (every mapped category must be one)."""
    return frozenset(load_prices().category)


def wweia_category(code: int | str) -> str | None:
    table = _wweia()
    key = str(code).strip()
    if key not in table:
        raise UnmappedCategory(f"WWEIA category {key} is not in wweia_categories.csv")
    return table[key]


def cofid_category(group: str) -> str | None:
    table = _cofid()
    group = group.strip().upper()
    for n in range(len(group), 0, -1):
        if group[:n] in table:
            return table[group[:n]]
    raise UnmappedCategory(f"CoFID group {group!r} is not covered by cofid_groups.csv")


def off_category(tags: Iterable[str]) -> str | None:
    """The category of the most specific mapped tag (OFF lists them general first)."""
    table = _off()
    return next((table[t] for t in reversed(list(tags)) if t in table), None)


@cache
def _wweia() -> dict[str, str | None]:
    return {r["code"]: _category(r, "wweia_categories.csv") for r in _rows("wweia_categories.csv")}


@cache
def _cofid() -> dict[str, str | None]:
    return {
        r["prefix"].strip().upper(): _category(r, "cofid_groups.csv")
        for r in _rows("cofid_groups.csv")
    }


@cache
def _off() -> dict[str, str | None]:
    return {
        r["tag"].strip(): _category(r, "off_categories.csv") for r in _rows("off_categories.csv")
    }


def _category(row: dict[str, str], name: str) -> str | None:
    category = row["category"].strip()
    if not category:
        if not row.get("note", "").strip():
            raise ValueError(f"{name}: a blank category needs a note: {row}")
        return None
    if category not in known_categories():
        raise ValueError(f"{name}: {category!r} is not a USDA category in prices.csv")
    return category


def _rows(name: str) -> list[dict[str, str]]:
    path = resources.files("larder_core") / "data" / name
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))
