from collections.abc import Callable
from datetime import UTC, date, datetime

import httpx

from larder_api.clock import get_clock
from larder_api.jobs import get_enqueue
from larder_api.main import app

Auth = Callable[..., dict[str, str]]

GOALS = {"kcal_min": 1800, "kcal_max": 2200, "weekly_budget_minor": 6000}
DUBLIN = {"country": "ie", "timezone": "Europe/Dublin", "locale": "en-IE"}


async def test_unsaved_region_defaults_to_gb(api: httpx.AsyncClient, auth: Auth) -> None:
    me = (await api.get("/me", headers=auth())).json()

    assert me["region"] == {
        "country": "GB",
        "name": "United Kingdom",
        "currency": "GBP",
        "locale": "en-GB",
        "timezone": "Europe/London",
        "saved": False,
    }


async def test_saving_ireland_switches_currency(api: httpx.AsyncClient, auth: Auth) -> None:
    await api.put("/me/goals", json=GOALS, headers=auth())

    put = await api.put("/me/region", json=DUBLIN, headers=auth())
    me = (await api.get("/me", headers=auth())).json()
    goals = (await api.get("/me/goals", headers=auth())).json()

    assert put.status_code == 200
    assert me["region"] == {
        "country": "IE",
        "name": "Ireland",
        "currency": "EUR",
        "locale": "en-IE",
        "timezone": "Europe/Dublin",
        "saved": True,
    }
    assert goals["currency"] == "EUR"
    assert goals["weekly_budget_minor"] == 6000  # the amount is kept


async def test_a_currency_the_user_picked_is_kept(api: httpx.AsyncClient, auth: Auth) -> None:
    await api.put("/me/goals", json=GOALS | {"currency": "USD"}, headers=auth())

    await api.put("/me/region", json=DUBLIN, headers=auth())

    goals = (await api.get("/me/goals", headers=auth())).json()
    assert goals["currency"] == "USD"


async def test_unknown_country_and_zone_are_refused(api: httpx.AsyncClient, auth: Auth) -> None:
    country = await api.put("/me/region", json={"country": "ZZ"}, headers=auth())
    zone = await api.put(
        "/me/region", json={"country": "IE", "timezone": "Mars/Olympus"}, headers=auth()
    )

    assert country.status_code == 400
    assert zone.status_code == 400
    assert "Mars/Olympus" in zone.json()["detail"][0]


async def test_regions_list_is_sorted_by_name(api: httpx.AsyncClient) -> None:
    names = [r["name"] for r in (await api.get("/regions")).json()]

    assert names == sorted(names)
    assert {"Ireland", "United Kingdom", "United States"} <= set(names)


async def test_receipt_date_defaults_to_the_users_local_day(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    # 23:30 UTC on 12 Aug is already 00:30 on 13 Aug in Dublin (Irish summer time, UTC+1).
    async def enqueue(upload_id: int) -> None:
        pass

    app.dependency_overrides[get_clock] = lambda: lambda: datetime(2026, 8, 12, 23, 30, tzinfo=UTC)
    app.dependency_overrides[get_enqueue] = lambda: enqueue
    try:
        await api.put("/me/region", json=DUBLIN, headers=auth())
        posted = await api.post("/pantry/receipts/text", json={"text": "MILK 1.20"}, headers=auth())
    finally:
        app.dependency_overrides.pop(get_clock, None)
        app.dependency_overrides.pop(get_enqueue, None)

    assert posted.status_code == 202
    assert date.fromisoformat(posted.json()["purchased_on"]) == date(2026, 8, 13)


def test_planner_weights_follow_the_currency() -> None:
    from larder_api.planning import weights_for
    from larder_solver import Weights

    gbp, eur = weights_for("GBP"), weights_for("EUR")
    assert gbp == Weights()
    assert eur.repeat == round(Weights().repeat * 1.17)
    assert (eur.cost, eur.waste) == (Weights().cost, Weights().waste)  # multipliers, unitless
