"""Estimated food prices (approximate UK supermarket averages), used for shopping cost and the
weekly budget. Estimates, not quotes: see docs/adr/0012-price-estimates.md."""

from typing import Literal

type Currency = Literal["GBP", "EUR", "USD"]


def price_per_kg(fdc_id: int, description: str, category: str | None, currency: Currency) -> int:
    """Estimated price in minor units (pence/cents) per kilogram (or per litre, for liquids
    weighed as grams). Lookup order: per-food override, keyword rule, USDA category default."""
    raise NotImplementedError
