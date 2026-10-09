"""Estimated food prices (approximate UK supermarket averages), used for shopping cost and the
weekly budget. Estimates, not quotes: see docs/adr/0012-price-estimates.md.

`data/prices.csv` (kind, key, pence_per_kg, shop, note): kind is `fdc` (one USDA food), `keyword`
(whole-word match on the description) or `category` (USDA category default). `shop=false` marks
things nobody buys (tap water, ice).
"""

from dataclasses import dataclass
from typing import Literal

type Currency = Literal["GBP", "EUR", "USD"]

# Fixed conversion of GBP estimates; documented approximations, not live rates.
PER_GBP: dict[Currency, float] = {"GBP": 1.0, "EUR": 1.17, "USD": 1.27}


@dataclass(frozen=True, slots=True)
class Price:
    pence_per_kg: int  # GBP pence per kilogram (or litre for liquids weighed as grams)
    shop: bool = True  # False: never on a shopping list (tap water)


def price(fdc_id: int, description: str, category: str | None) -> Price:
    """Estimated GBP price. Lookup order: fdc override, keyword rule, category default, global
    default."""
    raise NotImplementedError


def convert(pence_per_kg: int, currency: Currency) -> int:
    """GBP pence/kg -> minor units/kg of `currency` (rounded)."""
    return round(pence_per_kg * PER_GBP[currency])
