"""Where the user lives: currency, number/date locale, the default time zone and how far local
food prices sit from the UK table in data/prices.csv.

`country` is an ISO 3166-1 alpha-2 code. A user without one is treated as GB (the app's original
behaviour) until the web client saves the region it guessed from the browser.
"""

import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import cache
from importlib import resources
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from larder_core.prices import PER_GBP, Currency

__all__ = [
    "DEFAULT_COUNTRY",
    "REGIONS",
    "Region",
    "local_price",
    "local_today",
    "price_factor",
    "region_for",
    "valid_timezone",
]


@dataclass(frozen=True, slots=True)
class Region:
    country: str  # ISO 3166-1 alpha-2
    name: str  # "Ireland"
    currency: Currency
    locale: str  # BCP 47, for number and date formatting
    timezone: str  # IANA; the default when the browser doesn't say


def _euro(country: str, name: str, locale: str, timezone: str) -> Region:
    return Region(country, name, "EUR", locale, timezone)


REGIONS: dict[str, Region] = {
    r.country: r
    for r in (
        Region("IE", "Ireland", "EUR", "en-IE", "Europe/Dublin"),
        Region("GB", "United Kingdom", "GBP", "en-GB", "Europe/London"),
        Region("US", "United States", "USD", "en-US", "America/New_York"),
        _euro("AT", "Austria", "de-AT", "Europe/Vienna"),
        _euro("BE", "Belgium", "nl-BE", "Europe/Brussels"),
        _euro("HR", "Croatia", "hr-HR", "Europe/Zagreb"),
        _euro("CY", "Cyprus", "el-CY", "Asia/Nicosia"),
        _euro("EE", "Estonia", "et-EE", "Europe/Tallinn"),
        _euro("FI", "Finland", "fi-FI", "Europe/Helsinki"),
        _euro("FR", "France", "fr-FR", "Europe/Paris"),
        _euro("DE", "Germany", "de-DE", "Europe/Berlin"),
        _euro("GR", "Greece", "el-GR", "Europe/Athens"),
        _euro("IT", "Italy", "it-IT", "Europe/Rome"),
        _euro("LV", "Latvia", "lv-LV", "Europe/Riga"),
        _euro("LT", "Lithuania", "lt-LT", "Europe/Vilnius"),
        _euro("LU", "Luxembourg", "fr-LU", "Europe/Luxembourg"),
        _euro("MT", "Malta", "en-MT", "Europe/Malta"),
        _euro("NL", "Netherlands", "nl-NL", "Europe/Amsterdam"),
        _euro("PT", "Portugal", "pt-PT", "Europe/Lisbon"),
        _euro("SK", "Slovakia", "sk-SK", "Europe/Bratislava"),
        _euro("SI", "Slovenia", "sl-SI", "Europe/Ljubljana"),
        _euro("ES", "Spain", "es-ES", "Europe/Madrid"),
    )
}

DEFAULT_COUNTRY = "GB"


def region_for(country: str | None) -> Region:
    """The region for a country code (case-insensitive), GB when unset or unknown."""
    return REGIONS.get((country or "").upper(), REGIONS[DEFAULT_COUNTRY])


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def local_today(timezone: str | None, now: datetime) -> date:
    """The user's calendar date at `now` (UTC when the zone is unset or unknown)."""
    if timezone:
        try:
            return now.astimezone(ZoneInfo(timezone)).date()
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return now.astimezone(UTC).date()


@dataclass(frozen=True, slots=True)
class _Factors:
    default: float
    category: dict[str, float]


@cache
def _price_factors() -> dict[str, _Factors]:
    """data/price_regions.csv: (country, category, factor, note); category `*` is the default."""
    rows: dict[str, dict[str, float]] = {}
    path = resources.files("larder_core") / "data" / "price_regions.csv"
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            country, category = row["country"].strip().upper(), row["category"].strip()
            factor = float(row["factor"])
            if country not in REGIONS:
                raise ValueError(f"price_regions.csv: unknown country {country!r}")
            if not 0.3 <= factor <= 3:
                raise ValueError(f"price_regions.csv: {country} {category!r}: factor {factor}")
            per = rows.setdefault(country, {})
            if category in per:
                raise ValueError(f"price_regions.csv: duplicate row {country} {category!r}")
            per[category] = factor
    return {c: _Factors(per.pop("*", 1.0), per) for c, per in rows.items()}


def price_factor(country: str | None, category: str | None) -> float:
    """How local food prices compare with the UK table, for one food category (1.0 for GB)."""
    factors = _price_factors().get(region_for(country).country)
    if factors is None:
        return 1.0
    return factors.category.get(category or "", factors.default)


def local_price(
    pence_per_kg: int, category: str | None, country: str | None, currency: Currency
) -> int:
    """A UK-table price (GBP pence/kg) as an estimate for `country`, in `currency` minor units
    per kg (rounded)."""
    return round(pence_per_kg * price_factor(country, category) * PER_GBP[currency])
