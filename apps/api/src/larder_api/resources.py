from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

from fastapi import FastAPI, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from larder_api.settings import get_settings


@dataclass(frozen=True, slots=True)
class Resources:
    """Process-wide clients, created once in the app lifespan."""

    engine: AsyncEngine
    redis: Redis


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    # Both clients connect lazily, so the API starts even if a dependency is down;
    # /readyz reports that instead.
    resources = Resources(
        engine=create_async_engine(settings.database_url, pool_pre_ping=True),
        redis=Redis.from_url(settings.redis_url),  # pyright: ignore[reportUnknownMemberType]
    )
    app.state.resources = resources
    try:
        yield
    finally:
        await resources.redis.aclose()
        await resources.engine.dispose()


def get_resources(request: Request) -> Resources:
    return cast(Resources, request.app.state.resources)
