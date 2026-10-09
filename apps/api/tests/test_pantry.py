from collections.abc import Callable

import httpx
import pytest

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
