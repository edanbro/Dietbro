"""Barcode lookups: the local catalogue first, then the Open Food Facts product API for products
not imported yet (larder-data import-off brings in Ireland and the UK in bulk).

OFF asks clients to stay under 15 product reads a minute per IP and to identify themselves; we
keep a global budget (`off_rate_per_min`), a per-user hourly cap, and remember barcodes OFF
doesn't know for a day. Only the barcode is sent.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import httpx
from fastapi import Request
from redis.asyncio import Redis

from larder_api.settings import Settings, get_settings

FIELDS = (
    "code,product_name,product_name_en,generic_name,brands,countries_tags,categories_tags,"
    "allergens_tags,traces_tags,ingredients_text,ingredients_text_en,serving_quantity,"
    "product_quantity,nutriments"
)
MISS_TTL_S = 24 * 3600


class OffUnavailable(Exception):
    """Open Food Facts didn't answer (timeout, 5xx, rate limited)."""


class OffClient(Protocol):
    async def product(self, barcode: str) -> dict[str, Any] | None:
        """The product's fields, None when OFF doesn't know the barcode."""
        ...


@dataclass(frozen=True, slots=True)
class HttpOffClient:
    http: httpx.AsyncClient
    user_agent: str
    base_url: str

    async def product(self, barcode: str) -> dict[str, Any] | None:
        try:
            response = await self.http.get(
                f"{self.base_url}/api/v2/product/{barcode}.json",
                params={"fields": FIELDS},
                headers={"User-Agent": self.user_agent},
                timeout=5,
            )
        except httpx.HTTPError as exc:
            raise OffUnavailable(str(exc)) from exc
        if response.status_code == 404:
            return None
        if response.status_code == 429 or response.status_code >= 500:
            raise OffUnavailable(f"HTTP {response.status_code}")
        body = response.json()
        if body.get("status") != 1 or not isinstance(body.get("product"), dict):
            return None
        return cast(dict[str, Any], body["product"])


class Limits(Protocol):
    async def known_missing(self, barcode: str) -> bool: ...
    async def remember_missing(self, barcode: str) -> None: ...
    async def take_user(self, user_id: int) -> bool:
        """Count a lookup for the user; False when over the hourly cap."""
        ...

    async def take_global(self) -> bool:
        """Count a call to OFF; False when this minute's budget is spent."""
        ...


@dataclass(frozen=True, slots=True)
class RedisLimits:
    redis: Redis
    per_minute: int
    per_user_hour: int

    async def known_missing(self, barcode: str) -> bool:
        return bool(await self.redis.exists(f"off:miss:{barcode}"))

    async def remember_missing(self, barcode: str) -> None:
        await self.redis.set(f"off:miss:{barcode}", 1, ex=MISS_TTL_S)

    async def take_user(self, user_id: int) -> bool:
        hour = datetime.now(UTC).strftime("%Y%m%d%H")
        return await self._take(f"off:user:{user_id}:{hour}", self.per_user_hour, 3600)

    async def take_global(self) -> bool:
        minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
        return await self._take(f"off:rate:{minute}", self.per_minute, 60)

    async def _take(self, key: str, limit: int, ttl: int) -> bool:
        count = int(await self.redis.incr(key))
        if count == 1:
            await self.redis.expire(key, ttl)
        return count <= limit


def get_off_client(request: Request) -> OffClient | None:
    """None when lookups are off (no OFF_USER_AGENT): only imported products are found."""
    return cast(OffClient | None, getattr(request.app.state, "off", None))


def get_limits(request: Request) -> Limits:
    settings = get_settings()
    redis = cast(Redis, request.app.state.resources.redis)
    return RedisLimits(redis, settings.off_rate_per_min, settings.barcode_lookups_per_hour)


def make_off_client(settings: Settings, http: httpx.AsyncClient) -> OffClient | None:
    if not settings.off_user_agent:
        return None
    return HttpOffClient(http, settings.off_user_agent, settings.off_base_url.rstrip("/"))
