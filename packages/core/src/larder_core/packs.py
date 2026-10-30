"""How food is sold: the usual pack size, so a shopping list says "1 pack (320 g)" of tortillas
rather than "15 g", and what's left of the pack can go into the pantry.

`data/packs.csv` (kind, key, pack_g, note) uses the price table's lookup (larder_core.prices):
an `fdc` row for one food, else the `keyword` nearest the start of the description (most words
on a tie, then file order), else the food's `category`. `pack_g` 0 means sold loose, by count
or weight (onions, fresh fish): no rounding. Typical UK and Irish supermarket sizes; estimates.
"""

import csv
import math
from dataclasses import dataclass
from functools import cache
from importlib import resources

from larder_core.prices import description_words, find_words

MAX_PACK_G = 5_000


@dataclass(frozen=True, slots=True)
class PackTable:
    fdc: dict[int, int]
    keywords: tuple[tuple[tuple[str, ...], int], ...]  # most words first, then file order
    category: dict[str, int]


def pack_grams(fdc_id: int, description: str, category: str | None) -> int | None:
    """The usual pack in grams, or None when the food is sold loose or isn't listed."""
    table = load_packs()
    if fdc_id in table.fdc:
        grams = table.fdc[fdc_id]
    else:
        words = description_words(description)
        best: tuple[int, int] | None = None
        for keyword, found in table.keywords:
            at = find_words(words, keyword)
            if at is not None and (best is None or at < best[0]):
                best = (at, found)
        if best is not None:
            grams = best[1]
        elif category is not None and category in table.category:
            grams = table.category[category]
        else:
            return None
    return grams or None


def packs_for(grams: float, pack_g: int) -> int:
    """Whole packs that hold `grams` (at least one)."""
    return max(1, math.ceil(grams / pack_g - 1e-9))


@cache
def load_packs() -> PackTable:
    """data/packs.csv, validated."""
    fdc: dict[int, int] = {}
    keywords: dict[tuple[str, ...], int] = {}  # insertion (file) order
    category: dict[str, int] = {}
    path = resources.files("larder_core") / "data" / "packs.csv"
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kind, key = row["kind"], row["key"].strip()
            grams = int(row["pack_g"])
            if not 0 <= grams <= MAX_PACK_G:
                raise ValueError(f"packs.csv: {kind} {key!r}: {grams} g out of range")
            match kind:
                case "fdc":
                    _put(fdc, int(key), grams)
                case "keyword":
                    _put(keywords, description_words(key), grams)
                case "category":
                    _put(category, key, grams)
                case _:
                    raise ValueError(f"packs.csv: unknown kind {kind!r}")
    ordered = tuple(sorted(keywords.items(), key=lambda kv: -len(kv[0])))  # stable: file order
    return PackTable(fdc, ordered, category)


def _put[K](table: dict[K, int], key: K, grams: int) -> None:
    if key in table:
        raise ValueError(f"packs.csv: duplicate row for {key!r}")
    table[key] = grams
