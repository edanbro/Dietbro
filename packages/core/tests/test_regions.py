from datetime import UTC, date, datetime

import pytest

from larder_core.prices import load_prices
from larder_core.regions import (
    REGIONS,
    local_price,
    local_today,
    price_factor,
    region_for,
    valid_timezone,
)


def test_ireland() -> None:
    ie = region_for("ie")
    assert (ie.country, ie.currency, ie.locale, ie.timezone) == (
        "IE",
        "EUR",
        "en-IE",
        "Europe/Dublin",
    )


def test_unset_or_unknown_is_gb() -> None:
    assert region_for(None).country == "GB"
    assert region_for("ZZ").country == "GB"


def test_every_region_has_a_real_time_zone() -> None:
    assert all(valid_timezone(r.timezone) for r in REGIONS.values())
    assert not valid_timezone("Mars/Olympus")


@pytest.mark.parametrize(
    ("zone", "expected"),
    [
        ("Europe/Dublin", date(2026, 8, 13)),  # IST, UTC+1
        ("America/New_York", date(2026, 8, 12)),
        (None, date(2026, 8, 12)),
        ("not a zone", date(2026, 8, 12)),
    ],
)
def test_local_today(zone: str | None, expected: date) -> None:
    assert local_today(zone, datetime(2026, 8, 12, 23, 30, tzinfo=UTC)) == expected


def test_irish_prices_follow_the_cso_food_groups() -> None:
    assert price_factor("IE", "Dairy and Egg Products") == pytest.approx(1.11)
    assert price_factor("IE", "Some Unlisted Category") == pytest.approx(1.12)
    assert price_factor("GB", "Dairy and Egg Products") == 1.0
    assert price_factor("DE", None) == 1.0


def test_local_price_converts_and_adjusts() -> None:
    # 100p/kg of dairy in the UK -> x1.11 for Ireland -> x1.17 EUR per GBP.
    assert local_price(100, "Dairy and Egg Products", "IE", "EUR") == round(100 * 1.11 * 1.17)
    assert local_price(100, "Dairy and Egg Products", "GB", "GBP") == 100


def test_price_factor_categories_exist_in_the_price_table() -> None:
    from larder_core.regions import _price_factors  # pyright: ignore[reportPrivateUsage]

    known = set(load_prices().category)
    for factors in _price_factors().values():
        assert set(factors.category) <= known
