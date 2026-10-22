"""Rate limits (larder_api.ratelimit): fixed windows per user, per address or per token; 429 with
Retry-After over the limit; requests go ahead when Redis can't be reached."""

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi import Request
from redis.asyncio import Redis

from larder_api import recipe_import
from larder_api.main import app
from larder_api.ratelimit import MemoryCounter, RedisCounter, client_ip, get_counter
from larder_api.settings import Settings, get_settings

Auth = Callable[..., dict[str, str]]
FEED = "/calendar/" + "a" * 32 + ".ics"  # well-formed, but nobody's feed


@pytest.fixture
def counter() -> Iterator[MemoryCounter]:
    counter = MemoryCounter()
    app.dependency_overrides[get_counter] = lambda: counter
    yield counter
    app.dependency_overrides.pop(get_counter, None)


def limits(**overrides: int) -> None:
    settings = Settings(rate_limit_overrides=overrides)
    app.dependency_overrides[get_settings] = lambda: settings


@pytest.fixture(autouse=True)
def _restore_settings() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(get_settings, None)


async def test_over_the_limit_is_429_with_retry_after(
    api: httpx.AsyncClient, counter: MemoryCounter
) -> None:
    limits(calendar_feed=2)
    assert (await api.get(FEED)).status_code == 404
    assert (await api.get(FEED)).status_code == 404
    third = await api.get(FEED)
    assert third.status_code == 429
    assert 1 <= int(third.headers["retry-after"]) <= 3600
    assert third.json()["detail"] == ["Too many requests. Please try again a little later."]


async def test_each_token_has_its_own_count(api: httpx.AsyncClient, counter: MemoryCounter) -> None:
    limits(calendar_feed=1)
    assert (await api.get(FEED)).status_code == 404
    assert (await api.get(FEED)).status_code == 429
    other = "/calendar/" + "b" * 32 + ".ics"
    assert (await api.get(other)).status_code == 404


async def test_the_address_limit_covers_every_token(
    api: httpx.AsyncClient, counter: MemoryCounter
) -> None:
    limits(calendar_feed_ip=2)
    for letter in "ab":
        assert (await api.get(f"/calendar/{letter * 32}.ics")).status_code == 404
    assert (await api.get("/calendar/" + "c" * 32 + ".ics")).status_code == 429


async def test_users_are_counted_separately_and_nothing_is_fetched_over_the_limit(
    api: httpx.AsyncClient,
    auth: Auth,
    counter: MemoryCounter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched: list[str] = []

    async def fetch(url: str) -> Any:
        fetched.append(url)
        raise recipe_import.ImportError_("no recipe on that page")

    monkeypatch.setattr(recipe_import, "fetch_recipe", fetch)
    limits(import_read=1)
    body = {"url": "https://example.com/stew"}
    first = await api.post("/recipes/import/read", json=body, headers=auth("user_a"))
    assert first.status_code == 422
    second = await api.post("/recipes/import/read", json=body, headers=auth("user_a"))
    assert second.status_code == 429
    assert len(fetched) == 1
    other = await api.post("/recipes/import/read", json=body, headers=auth("user_b"))
    assert other.status_code == 422


async def test_signed_out_requests_are_refused_before_counting(
    api: httpx.AsyncClient, counter: MemoryCounter
) -> None:
    limits(import_read=0)
    response = await api.post("/recipes/import/read", json={"url": "https://example.com"})
    assert response.status_code == 401
    assert counter.counts == {}


async def test_limits_can_be_turned_off(api: httpx.AsyncClient, counter: MemoryCounter) -> None:
    settings = Settings(rate_limits=False, rate_limit_overrides={"calendar_feed": 0})
    app.dependency_overrides[get_settings] = lambda: settings
    assert (await api.get(FEED)).status_code == 404


async def test_requests_go_ahead_when_redis_is_down(
    api: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    class Down:
        async def hit(self, key: str, window_s: int) -> int:
            raise ConnectionError("redis is down")

    app.dependency_overrides[get_counter] = Down
    try:
        limits(calendar_feed=0)
        assert (await api.get(FEED)).status_code == 404
        assert "not checked" in caplog.text
    finally:
        app.dependency_overrides.pop(get_counter, None)


def request(peer: str, *forwarded: str) -> Request:
    headers = [(b"x-forwarded-for", v.encode()) for v in forwarded]
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_the_client_address_is_the_peer_unless_proxies_are_trusted() -> None:
    req = request("10.0.0.5", "203.0.113.9")
    assert client_ip(req, Settings(trusted_proxy_hops=0)) == "10.0.0.5"
    assert client_ip(req, Settings(trusted_proxy_hops=1)) == "203.0.113.9"


def test_a_forged_forwarded_for_entry_is_ignored() -> None:
    # The client sent "1.2.3.4"; our proxy appended the address it saw.
    req = request("10.0.0.5", "1.2.3.4, 203.0.113.9")
    assert client_ip(req, Settings(trusted_proxy_hops=1)) == "203.0.113.9"
    # Two proxies of ours: the outer one's entry, two from the right.
    req = request("10.0.0.5", "1.2.3.4, 203.0.113.9", "10.0.0.2")
    assert client_ip(req, Settings(trusted_proxy_hops=2)) == "203.0.113.9"


def test_too_few_forwarded_entries_fall_back_to_the_peer() -> None:
    assert client_ip(request("10.0.0.5"), Settings(trusted_proxy_hops=1)) == "10.0.0.5"


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(Settings().redis_url)  # pyright: ignore[reportUnknownMemberType]
    try:
        await client.ping()  # pyright: ignore[reportUnknownMemberType]
    except Exception:
        await client.aclose()
        pytest.skip("no Redis")
    yield client
    await client.aclose()


async def test_redis_counts_within_a_window_that_expires(redis: Redis) -> None:
    key = "rl:test:counter"
    await redis.delete(key)
    counter = RedisCounter(redis)
    assert [await counter.hit(key, 60) for _ in range(3)] == [1, 2, 3]
    ttl = await redis.ttl(key)
    assert 0 < ttl <= 60
    await counter.hit(key, 600)  # a later hit never extends the window
    assert await redis.ttl(key) <= 60
    await redis.delete(key)
