"""Barcode lookups: local products first, then Open Food Facts (faked here), with limits."""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.barcodes import HttpOffClient, OffUnavailable, get_limits, get_off_client
from larder_api.main import app
from larder_db.engine import make_sessionmaker
from larder_db.models import LOCAL_ID_START, Food

Auth = Callable[..., dict[str, str]]

KNOWN = "4006381333931"
NEW = "5000159407236"
BUTTER = 173410

OFF_BUTTER: dict[str, Any] = {
    "code": NEW,
    "product_name": "Pure Irish Butter",
    "brands": "Kerrygold",
    "countries_tags": ["en:united-kingdom"],
    "categories_tags": ["en:dairies", "en:butters"],
    "allergens_tags": ["en:milk"],
    "product_quantity": 227,
    "nutriments": {"energy-kcal_100g": 740, "fat_100g": 82, "proteins_100g": 0.5},
}


@dataclass
class FakeOff:
    products: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    down: bool = False
    calls: list[str] = field(default_factory=list[str])

    async def product(self, barcode: str) -> dict[str, Any] | None:
        self.calls.append(barcode)
        if self.down:
            raise OffUnavailable("down")
        return self.products.get(barcode)


@dataclass
class FakeLimits:
    user_left: int = 10
    global_left: int = 10
    missing: set[str] = field(default_factory=set[str])

    async def known_missing(self, barcode: str) -> bool:
        return barcode in self.missing

    async def remember_missing(self, barcode: str) -> None:
        self.missing.add(barcode)

    async def take_user(self, user_id: int) -> bool:
        self.user_left -= 1
        return self.user_left >= 0

    async def take_global(self) -> bool:
        self.global_left -= 1
        return self.global_left >= 0


@pytest.fixture
async def products(db_engine: AsyncEngine) -> None:
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            [
                Food(
                    id=BUTTER,
                    description="Butter, salted",
                    data_type="sr_legacy",
                    category="Dairy and Egg Products",
                    kcal=717,
                    protein_g=0.9,
                    fat_g=81,
                ),
                Food(
                    id=LOCAL_ID_START + 1,
                    source="off",
                    source_id=KNOWN,
                    barcode=KNOWN,
                    description="Cheddar",
                    brand="Kerrygold",
                    data_type="branded",
                    category="Dairy and Egg Products",
                    countries=["IE"],
                    kcal=410,
                ),
            ]
        )
        await session.commit()


@pytest.fixture
async def off(api: httpx.AsyncClient) -> AsyncIterator[tuple[FakeOff, FakeLimits]]:
    fake, limits = FakeOff({NEW: OFF_BUTTER}), FakeLimits()
    app.dependency_overrides[get_off_client] = lambda: fake
    app.dependency_overrides[get_limits] = lambda: limits
    yield fake, limits
    app.dependency_overrides.pop(get_off_client, None)
    app.dependency_overrides.pop(get_limits, None)


@pytest.mark.usefixtures("products")
async def test_known_barcode_is_found_locally(
    api: httpx.AsyncClient, auth: Auth, off: tuple[FakeOff, FakeLimits]
) -> None:
    response = await api.get(f"/foods/barcode/{KNOWN}", headers=auth())

    assert response.status_code == 200
    assert (response.json()["brand"], response.json()["description"]) == ("Kerrygold", "Cheddar")
    assert off[0].calls == []


@pytest.mark.usefixtures("products")
async def test_new_barcode_is_fetched_once_then_local(
    api: httpx.AsyncClient, auth: Auth, off: tuple[FakeOff, FakeLimits], db_engine: AsyncEngine
) -> None:
    await api.put("/me/region", json={"country": "IE"}, headers=auth())

    first = await api.get(f"/foods/barcode/{NEW}", headers=auth())
    again = await api.get(f"/foods/barcode/{NEW}", headers=auth())

    assert first.status_code == again.status_code == 200
    detail = first.json()
    assert (detail["kind"], detail["brand"], detail["barcode"]) == ("product", "Kerrygold", NEW)
    assert detail["counts_as"]["id"] == BUTTER  # "butter" (same category)
    assert detail["units"][0] == {"unit": "packet", "grams_each": 227.0}
    assert "milk" in detail["allergens"]
    assert off[0].calls == [NEW]
    async with make_sessionmaker(db_engine)() as session:
        food = await session.scalar(select(Food).where(Food.barcode == NEW))
        assert food is not None
        assert (food.origin, food.countries) == ("lookup", ["GB", "IE"])  # scanned in Ireland


@pytest.mark.usefixtures("products")
async def test_unknown_barcode_is_remembered(
    api: httpx.AsyncClient, auth: Auth, off: tuple[FakeOff, FakeLimits]
) -> None:
    unknown = "96385074"
    first = await api.get(f"/foods/barcode/{unknown}", headers=auth())
    second = await api.get(f"/foods/barcode/{unknown}", headers=auth())

    assert first.status_code == second.status_code == 404
    assert "Search for the food by name" in first.json()["detail"][0]
    assert off[0].calls == [unknown]


@pytest.mark.usefixtures("products")
async def test_invalid_barcode(
    api: httpx.AsyncClient, auth: Auth, off: tuple[FakeOff, FakeLimits]
) -> None:
    assert (await api.get("/foods/barcode/1234", headers=auth())).status_code == 422


@pytest.mark.usefixtures("products")
async def test_limits_and_outages(
    api: httpx.AsyncClient, auth: Auth, off: tuple[FakeOff, FakeLimits]
) -> None:
    fake, limits = off
    limits.user_left = 0
    assert (await api.get(f"/foods/barcode/{NEW}", headers=auth())).status_code == 429

    limits.user_left, limits.global_left = 10, 0
    busy = await api.get(f"/foods/barcode/{NEW}", headers=auth())
    assert (busy.status_code, busy.headers["retry-after"]) == (503, "60")

    limits.global_left, fake.down = 10, True
    assert (await api.get(f"/foods/barcode/{NEW}", headers=auth())).status_code == 503


@pytest.mark.usefixtures("products")
async def test_lookups_off_without_a_user_agent(api: httpx.AsyncClient, auth: Auth) -> None:
    app.dependency_overrides[get_off_client] = lambda: None
    app.dependency_overrides[get_limits] = FakeLimits
    try:
        local = await api.get(f"/foods/barcode/{KNOWN}", headers=auth())
        new = await api.get(f"/foods/barcode/{NEW}", headers=auth())
    finally:
        app.dependency_overrides.pop(get_off_client, None)
        app.dependency_overrides.pop(get_limits, None)

    assert (local.status_code, new.status_code) == (200, 404)


async def test_http_client_sends_only_the_barcode_and_a_user_agent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if NEW in request.url.path:
            return httpx.Response(200, json={"status": 1, "product": OFF_BUTTER})
        return httpx.Response(404, json={"status": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = HttpOffClient(http, "Mealwright/test (dev@example.com)", "https://off.test")
        assert await client.product(NEW) == OFF_BUTTER
        assert await client.product("96385074") is None

    assert seen[0].url.path == f"/api/v2/product/{NEW}.json"
    assert seen[0].headers["user-agent"] == "Mealwright/test (dev@example.com)"
    assert "authorization" not in seen[0].headers
