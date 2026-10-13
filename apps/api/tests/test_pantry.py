from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.clock import get_clock
from larder_api.main import app
from larder_db.engine import make_sessionmaker
from larder_db.models import PantryItem

Auth = Callable[..., dict[str, str]]

ONION, OLIVE_OIL = 170000, 171413  # seeded by the `foods` fixture

pytestmark = pytest.mark.usefixtures("foods")


async def add(
    api: httpx.AsyncClient, auth: Auth, user: str = "user_a", **body: object
) -> httpx.Response:
    payload = {"food_id": ONION, "quantity": 2, "unit": "large"} | body
    return await api.post("/pantry", json=payload, headers=auth(user))


async def test_add_converts_to_grams(api: httpx.AsyncClient, auth: Auth) -> None:
    onions = await add(api, auth, expires_on="2026-10-20")
    oil = await add(api, auth, food_id=OLIVE_OIL, quantity=3, unit="tbsp", approx=True)

    assert onions.status_code == 201
    assert onions.json()["grams"] == 300
    assert onions.json()["food"]["description"] == "Onions, raw"
    assert oil.json()["grams"] == pytest.approx(40.5)
    assert oil.json()["approx"] is True


async def test_list_is_soonest_expiry_first(api: httpx.AsyncClient, auth: Auth) -> None:
    await add(api, auth, expires_on=None, quantity=1)
    await add(api, auth, expires_on="2026-11-01", quantity=2)
    await add(api, auth, expires_on="2026-10-10", quantity=3)

    items = (await api.get("/pantry", headers=auth())).json()

    assert [i["quantity"] for i in items] == [3, 2, 1]


async def test_used_up_items_are_not_listed(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    kept = (await add(api, auth)).json()
    used = (await add(api, auth)).json()
    async with make_sessionmaker(db_engine)() as session:
        await session.execute(update(PantryItem).where(PantryItem.id == used["id"]).values(grams=0))
        await session.commit()

    items = (await api.get("/pantry", headers=auth())).json()

    assert [i["id"] for i in items] == [kept["id"]]


async def test_update_recomputes_grams(api: httpx.AsyncClient, auth: Auth) -> None:
    item = (await add(api, auth)).json()

    patched = await api.patch(
        f"/pantry/{item['id']}", json={"quantity": 500, "unit": "g"}, headers=auth()
    )

    assert patched.json()["grams"] == 500
    assert patched.json()["unit"] == "g"


async def test_delete(api: httpx.AsyncClient, auth: Auth) -> None:
    item = (await add(api, auth)).json()

    assert (await api.delete(f"/pantry/{item['id']}", headers=auth())).status_code == 204
    assert (await api.get("/pantry", headers=auth())).json() == []


async def test_other_users_items_are_invisible(api: httpx.AsyncClient, auth: Auth) -> None:
    item = (await add(api, auth, user="user_a")).json()
    other = auth("user_b")

    assert (await api.get("/pantry", headers=other)).json() == []
    assert (
        await api.patch(f"/pantry/{item['id']}", json={"quantity": 1}, headers=other)
    ).status_code == 404
    assert (await api.delete(f"/pantry/{item['id']}", headers=other)).status_code == 404
    assert len((await api.get("/pantry", headers=auth("user_a"))).json()) == 1


async def test_unconvertible_unit_is_400(api: httpx.AsyncClient, auth: Auth) -> None:
    response = await add(api, auth, food_id=OLIVE_OIL, quantity=1, unit="large")

    assert response.status_code == 400
    assert "can't convert" in response.json()["detail"][0]


async def test_unknown_food_is_404(api: httpx.AsyncClient, auth: Auth) -> None:
    assert (await add(api, auth, food_id=999)).status_code == 404


async def test_food_search_puts_curated_names_first(api: httpx.AsyncClient, auth: Auth) -> None:
    results = (await api.get("/foods/search", params={"q": "onion"}, headers=auth())).json()

    assert results[0]["description"] == "Onions, raw"
    assert "Onion rings, frozen" in [r["description"] for r in results]


async def test_food_units(api: httpx.AsyncClient, auth: Auth) -> None:
    food = (await api.get(f"/foods/{ONION}", headers=auth())).json()

    units = {u["unit"]: u["grams_each"] for u in food["units"]}
    assert units["g"] == 1
    assert units["large"] == 150
    assert "cup" in units
    assert (await api.get("/foods/999", headers=auth())).status_code == 404


async def test_food_search_needs_auth(api: httpx.AsyncClient) -> None:
    assert (await api.get("/foods/search", params={"q": "onion"})).status_code == 401


async def test_expiring_lists_items_due_within_days_soonest_first(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    for quantity, expires in [(1, "2026-10-09"), (2, "2026-10-12"), (3, "2026-10-14"), (4, None)]:
        await add(api, auth, quantity=quantity, expires_on=expires)
    await add(api, auth, quantity=5, expires_on="2026-10-15")
    await add(api, auth, user="user_b", expires_on="2026-10-12")
    eaten = (await add(api, auth, quantity=6, expires_on="2026-10-12")).json()
    async with make_sessionmaker(db_engine)() as session:  # used up by eaten meals
        await session.execute(
            update(PantryItem).where(PantryItem.id == eaten["id"]).values(grams=0)
        )
        await session.commit()

    soon = (await api.get("/pantry/expiring?today=2026-10-12", headers=auth())).json()
    week = (await api.get("/pantry/expiring?today=2026-10-12&days=7", headers=auth())).json()

    assert (soon["today"], soon["days"], soon["expired"]) == ("2026-10-12", 3, 1)
    assert [(i["quantity"], i["days_left"]) for i in soon["items"]] == [(1, -3), (2, 0), (3, 2)]
    assert [i["quantity"] for i in week["items"]] == [1, 2, 3, 5]


async def test_me_counts_expiring_items(api: httpx.AsyncClient, auth: Auth) -> None:
    app.dependency_overrides[get_clock] = lambda: lambda: datetime(2026, 10, 12, 9, tzinfo=UTC)
    try:
        await add(api, auth, expires_on="2026-10-13")
        await add(api, auth, expires_on="2026-10-30")
        me = (await api.get("/me", headers=auth())).json()
    finally:
        app.dependency_overrides.pop(get_clock, None)

    assert me["profile"]["expiring_soon"] == 1
    assert me["profile"]["pantry_items"] == 2
