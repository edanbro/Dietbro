import asyncio
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

from larder_api.health import Check, get_checks
from larder_api.main import app


async def ok() -> None:
    return None


async def fail() -> None:
    raise ConnectionError("down")


@pytest.fixture
def override_checks() -> Iterator[dict[str, Check]]:
    checks: dict[str, Check] = {}
    app.dependency_overrides[get_checks] = lambda: checks
    yield checks
    app.dependency_overrides.clear()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_healthz(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_all_ok(client: httpx.AsyncClient, override_checks: dict[str, Check]) -> None:
    override_checks.update(database=ok, redis=ok)

    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_readyz_degraded_when_a_check_fails(
    client: httpx.AsyncClient, override_checks: dict[str, Check]
) -> None:
    override_checks.update(database=ok, redis=fail)

    response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "checks": {"database": "ok", "redis": "error"}}


async def test_readyz_times_out_slow_checks(
    client: httpx.AsyncClient,
    override_checks: dict[str, Check],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def hang() -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr("larder_api.health.CHECK_TIMEOUT_S", 0.01)
    override_checks.update(database=hang)

    response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "error"}
