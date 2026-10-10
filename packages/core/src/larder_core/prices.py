"""Estimated food prices (approximate UK supermarket averages), used for shopping cost and the
weekly budget. Estimates, not quotes: see docs/adr/0012-price-estimates.md.

`data/prices.csv` (kind, key, pence_per_kg, shop, note): kind is `fdc` (one USDA food), `keyword`
(whole-word match on the description) or `category` (USDA category default). `shop=false` marks
things nobody buys (tap water, ice).

Keywords match whole words, singular or plural, in order ("pepper black" matches "Spices, pepper,
black"). USDA descriptions lead with the food ("Cookies, chocolate sandwich"), so when several
keywords match, the match nearest the start wins, then the one with the most words, then the
earlier row.
"""

import csv
import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Literal

from larder_core.names import singular

type Currency = Literal["GBP", "EUR", "USD"]

# Fixed conversion of GBP estimates; documented approximations, not live rates.
PER_GBP: dict[Currency, float] = {"GBP": 1.0, "EUR": 1.17, "USD": 1.27}


@dataclass(frozen=True, slots=True)
class Price:
    pence_per_kg: int  # GBP pence per kilogram (or litre for liquids weighed as grams)
    shop: bool = True  # False: never on a shopping list (tap water)


# When neither the food, a keyword nor its category is in the table.
DEFAULT_PRICE = Price(600)
MAX_PENCE_PER_KG = 1_000_000  # saffron is about £6,000/kg


def price(fdc_id: int, description: str, category: str | None) -> Price:
    """Estimated GBP price. Lookup order: fdc override, keyword rule, category default, global
    default."""
    table = load_prices()
    if fdc_id in table.fdc:
        return table.fdc[fdc_id]
    words = _words(description)
    best: tuple[int, Price] | None = None
    for keyword, found in table.keywords:
        at = _find(words, keyword)
        if at is not None and (best is None or at < best[0]):
            best = (at, found)
    if best is not None:
        return best[1]
    if category is not None and category in table.category:
        return table.category[category]
    return DEFAULT_PRICE


def convert(pence_per_kg: int, currency: Currency) -> int:
    """GBP pence/kg -> minor units/kg of `currency` (rounded)."""
    return round(pence_per_kg * PER_GBP[currency])


@dataclass(frozen=True, slots=True)
class PriceTable:
    fdc: dict[int, Price]
    keywords: tuple[tuple[tuple[str, ...], Price], ...]  # most words first, then file order
    category: dict[str, Price]


@cache
def load_prices() -> PriceTable:
    """data/prices.csv, validated."""
    fdc: dict[int, Price] = {}
    keywords: dict[tuple[str, ...], Price] = {}  # insertion (file) order
    category: dict[str, Price] = {}
    path = resources.files("larder_core") / "data" / "prices.csv"
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kind, key = row["kind"], row["key"].strip()
            pence = int(row["pence_per_kg"])
            if not 0 <= pence <= MAX_PENCE_PER_KG:
                raise ValueError(f"prices.csv: {kind} {key!r}: {pence} p/kg out of range")
            if row["shop"] not in ("true", "false"):
                raise ValueError(f"prices.csv: {kind} {key!r}: shop must be true or false")
            found = Price(pence, row["shop"] == "true")
            match kind:
                case "fdc":
                    _put(fdc, int(key), found)
                case "keyword":
                    _put(keywords, _words(key), found)
                case "category":
                    _put(category, key, found)
                case _:
                    raise ValueError(f"prices.csv: unknown kind {kind!r}")
    ordered = tuple(sorted(keywords.items(), key=lambda kv: -len(kv[0])))  # stable: file order
    return PriceTable(fdc, ordered, category)


def _put[K](table: dict[K, Price], key: K, found: Price) -> None:
    if key in table:
        raise ValueError(f"prices.csv: duplicate row for {key!r}")
    table[key] = found


def _words(text: str) -> tuple[str, ...]:
    folded = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return tuple(singular(w) for w in re.findall(r"[a-z0-9]+", folded))


def _find(words: tuple[str, ...], keyword: tuple[str, ...]) -> int | None:
    """Index of the first occurrence of `keyword` in `words`."""
    n = len(keyword)
    return next((i for i in range(len(words) - n + 1) if words[i : i + n] == keyword), None)
