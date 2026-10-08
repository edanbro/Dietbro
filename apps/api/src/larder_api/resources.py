from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

import httpx
from fastapi import FastAPI, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.auth import JWKSCache, TokenVerifier
from larder_api.settings import Settings, get_settings
from larder_db.engine import make_engine, make_sessionmaker


@dataclass(frozen=True, slots=True)
class Resources:
    """Process-wide clients, created once in the app lifespan."""

    engine: AsyncEngine
    redis: Redis


def make_verifier(settings: Settings, client: httpx.AsyncClient) -> TokenVerifier | None:
    if not settings.clerk_issuer or not settings.jwks_url:
        return None
    url = settings.jwks_url

    async def fetch() -> dict[str, Any]:
        response = await client.get(url, timeout=5)
        response.raise_for_status()
        return response.json()

    return TokenVerifier(
        issuer=settings.clerk_issuer,
        jwks=JWKSCache(fetch),
        authorized_parties=settings.clerk_authorized_parties or settings.cors_origins,
    )


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
    try:
        yield
    finally:
        await http.aclose()
        await resources.redis.aclose()
        await resources.engine.dispose()


def get_resources(request: Request) -> Resources:
    return cast(Resources, request.app.state.resources)
