import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

import httpx
from fastapi import FastAPI, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from larder_api.auth import JWKSCache, TokenVerifier
from larder_api.planning import CatalogCache
from larder_api.settings import Settings, get_settings
from larder_db.engine import make_engine, make_sessionmaker


@dataclass(frozen=True, slots=True)
class Resources:
    """Process-wide clients, created once in the app lifespan."""

    engine: AsyncEngine
    redis: Redis


def make_verifier(settings: Settings, client: httpx.AsyncClient) -> TokenVerifier | None:
    issuer, url = settings.issuer, settings.jwks_url
    if not issuer or not url:
        return None

    async def fetch() -> dict[str, Any]:
        response = await client.get(url, timeout=5)
        response.raise_for_status()
        return response.json()

    return TokenVerifier(
        issuer=issuer,
        jwks=JWKSCache(fetch),
        authorized_parties=settings.clerk_authorized_parties or settings.cors_origins,
    )


logger = logging.getLogger(__name__)


async def _warm(cache: CatalogCache, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    try:
        await cache.get(sessionmaker)
    except Exception:  # the DB may not be ready yet; the first plan request loads it instead
        logger.warning("planning catalog warm-up failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    # Clients connect lazily, so the API starts even if a dependency is down;
    # /readyz reports that instead.
    resources = Resources(
        engine=make_engine(settings.database_url, pool_pre_ping=True),
        redis=Redis.from_url(settings.redis_url),  # pyright: ignore[reportUnknownMemberType]
    )
    http = httpx.AsyncClient()
    app.state.resources = resources
    app.state.sessionmaker = make_sessionmaker(resources.engine)
    app.state.verifier = make_verifier(settings, http)
    # Build the planning catalog in the background so the first plan doesn't pay for it.
    app.state.catalog = CatalogCache()
    warm = asyncio.create_task(_warm(app.state.catalog, app.state.sessionmaker))
    try:
        yield
    finally:
        warm.cancel()
        await http.aclose()
        await resources.redis.aclose()
        await resources.engine.dispose()


def get_resources(request: Request) -> Resources:
    return cast(Resources, request.app.state.resources)
