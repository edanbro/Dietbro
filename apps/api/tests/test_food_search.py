"""Food search across sources (USDA, CoFID, Open Food Facts products), product details, and
products counting as their generic food once they're in a pantry."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_db.engine import make_sessionmaker
from larder_db.models import LOCAL_ID_START, Food, FoodPortion

Auth = Callable[..., dict[str, str]]

BUTTER = 173410  # "Butter, salted" (an alias: "butter")
CHIPS = 19411
COFID_BUTTER = LOCAL_ID_START + 1
KERRYGOLD = LOCAL_ID_START + 2
FRENCH_ONLY = LOCAL_ID_START + 3
TAYTO = LOCAL_ID_START + 4
DAIRY = "Dairy and Egg Products"


@pytest.fixture
async def catalog(db_engine: AsyncEngine) -> None:
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            [
                Food(
                    id=BUTTER,
                    description="Butter, salted",
                    data_type="sr_legacy",
                    category=DAIRY,
                    kcal=717,
                    protein_g=0.9,
                    fat_g=81,
                    portions=[FoodPortion(amount=1, unit="tbsp", grams=14.2)],
                ),
                Food(
                    id=CHIPS,
                    description="Snacks, potato chips, plain, salted",
                    data_type="sr_legacy",
                    category="Snacks",
                    kcal=536,
                ),
                Food(
                    id=COFID_BUTTER,
                    source="cofid",
                    source_id="17-001",
                    description="Butter, salted",
                    data_type="cofid",
                    category=DAIRY,
                    kcal=744,
                    generic_food_id=BUTTER,
                    generic_method="curated",
                ),
                Food(
                    id=KERRYGOLD,
                    source="off",
                    source_id="5011038100013",
                    barcode="4006381333931",
                    description="Pure Irish Butter",
                    brand="Kerrygold",
                    data_type="branded",
                    category=DAIRY,
                    countries=["IE", "GB"],
                    allergens_declared=["milk"],
                    kcal=740,
                    protein_g=0.5,
                    fat_g=82,
                    portions=[FoodPortion(amount=1, unit="packet", grams=227)],
                ),
                Food(
                    id=FRENCH_ONLY,
                    source="off",
                    source_id="3000000000001",
                    description="Beurre doux",
                    brand="Président",
                    data_type="branded",
                    category=DAIRY,
                    countries=["FR"],
                    kcal=740,
                ),
                Food(
                    id=TAYTO,
                    source="off",
                    source_id="5099999999999",
                    description="Cheese & Onion Crisps",
                    brand="Tayto",
                    data_type="branded",
                    category="Snacks",
                    countries=["IE"],
                    traces_declared=["milk"],
                    kcal=530,
                ),
            ]
        )
        await session.commit()


async def search(api: httpx.AsyncClient, auth: Auth, **params: Any) -> list[dict[str, Any]]:
    response = await api.get("/foods/search", params=params, headers=auth())
    assert response.status_code == 200, response.text
    return response.json()


async def in_ireland(api: httpx.AsyncClient, auth: Auth) -> None:
    await api.put("/me/region", json={"country": "IE"}, headers=auth())


@pytest.mark.usefixtures("catalog")
async def test_generic_foods_come_before_products(api: httpx.AsyncClient, auth: Auth) -> None:
    await in_ireland(api, auth)

    results = await search(api, auth, q="butter")

    ids = [r["id"] for r in results]
    assert ids[0] == BUTTER  # the curated name leads
    assert ids.index(COFID_BUTTER) < ids.index(KERRYGOLD)
    product = next(r for r in results if r["id"] == KERRYGOLD)
    assert (product["kind"], product["brand"], product["source"]) == ("product", "Kerrygold", "off")


@pytest.mark.usefixtures("catalog")
async def test_products_are_only_those_sold_in_the_users_country(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    await in_ireland(api, auth)

    ids = {r["id"] for r in await search(api, auth, q="butter")}
    beurre = {r["id"] for r in await search(api, auth, q="beurre")}

    assert KERRYGOLD in ids
    assert FRENCH_ONLY not in ids | beurre


@pytest.mark.usefixtures("catalog")
async def test_brand_names_are_searchable(api: httpx.AsyncClient, auth: Auth) -> None:
    await in_ireland(api, auth)

    assert [r["id"] for r in await search(api, auth, q="kerrygold")] == [KERRYGOLD]
    assert TAYTO in {r["id"] for r in await search(api, auth, q="tayto")}


@pytest.mark.usefixtures("catalog")
async def test_british_words_find_us_foods(api: httpx.AsyncClient, auth: Auth) -> None:
    await in_ireland(api, auth)

    ids = [r["id"] for r in await search(api, auth, q="crisps")]

    assert CHIPS in ids  # "crisps" -> "potato chips"
    assert TAYTO in ids


@pytest.mark.usefixtures("catalog")
async def test_generic_scope_and_short_queries_leave_products_out(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    await in_ireland(api, auth)

    generic = {r["kind"] for r in await search(api, auth, q="butter", scope="generic")}
    assert generic == {"food"}


@pytest.mark.usefixtures("catalog")
async def test_products_need_a_supported_country(api: httpx.AsyncClient, auth: Auth) -> None:
    await api.put("/me/region", json={"country": "US"}, headers=auth())

    kinds = {r["kind"] for r in await search(api, auth, q="butter")}

    assert kinds == {"food"}


@pytest.mark.usefixtures("catalog")
async def test_pages_dont_repeat(api: httpx.AsyncClient, auth: Auth) -> None:
    await in_ireland(api, auth)

    first = await search(api, auth, q="butter", limit=2)
    second = await search(api, auth, q="butter", limit=2, offset=2)

    assert len(first) == 2
    assert not {r["id"] for r in first} & {r["id"] for r in second}


@pytest.mark.usefixtures("catalog")
async def test_product_detail(api: httpx.AsyncClient, auth: Auth) -> None:
    detail = (await api.get(f"/foods/{KERRYGOLD}", headers=auth())).json()
    crisps = (await api.get(f"/foods/{TAYTO}", headers=auth())).json()

    assert detail["units"][0] == {"unit": "packet", "grams_each": 227.0}
    assert "milk" in detail["allergens"]
    assert detail["barcode"] == "4006381333931"
    assert "Open Food Facts" in detail["attribution"]
    assert crisps["may_contain"] == ["milk"]
    assert "milk" in crisps["allergens"]  # traces count: the safe side


@pytest.mark.usefixtures("catalog")
async def test_regional_food_counts_as_its_generic(api: httpx.AsyncClient, auth: Auth) -> None:
    detail = (await api.get(f"/foods/{COFID_BUTTER}", headers=auth())).json()

    assert detail["counts_as"]["id"] == BUTTER
    assert "tbsp" in {u["unit"] for u in detail["units"]}  # the generic's portions


@pytest.mark.usefixtures("catalog")
async def test_adding_a_product_links_it_to_its_generic(
    api: httpx.AsyncClient, auth: Auth, db_engine: AsyncEngine
) -> None:
    added = await api.post(
        "/pantry", json={"food_id": KERRYGOLD, "quantity": 1, "unit": "packet"}, headers=auth()
    )

    assert added.status_code == 201, added.text
    assert added.json()["grams"] == 227
    async with make_sessionmaker(db_engine)() as session:
        food = await session.get(Food, KERRYGOLD)
        assert food is not None
        assert (food.generic_food_id, food.generic_method) == (BUTTER, "curated")


@pytest.mark.usefixtures("catalog")
async def test_avoiding_a_regional_food_avoids_its_generic(
    api: httpx.AsyncClient, auth: Auth
) -> None:
    saved = await api.put(
        "/me/allergies", json={"allergens": [], "avoid_food_ids": [COFID_BUTTER]}, headers=auth()
    )

    assert saved.json()["avoid_food_ids"] == [BUTTER, COFID_BUTTER]
