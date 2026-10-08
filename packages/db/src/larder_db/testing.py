"""Pytest fixtures for tests that need Postgres. Registered in the repo-root conftest.py.

Uses $TEST_DATABASE_URL (default: the compose database server, database `larder_test`).
Tests are skipped when the server is unreachable, unless LARDER_REQUIRE_DB=1 (set in CI).
"""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from larder_db.engine import make_engine, make_sessionmaker
from larder_db.models import Base

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://larder:larder@localhost:5432/larder_test"
ALEMBIC_INI = os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")


def alembic_config(url: str) -> Config:
    config = Config(os.path.abspath(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


async def _ensure_database(url: str) -> None:
    parsed = make_url(url)
    admin = create_async_engine(
        parsed.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args={"timeout": 3}
    )
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": parsed.database}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    finally:
        await admin.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of an existing, empty-or-ours test database (created if missing)."""
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    try:
        asyncio.run(_ensure_database(url))
    except (OSError, TimeoutError, DBAPIError) as exc:
        if os.environ.get("LARDER_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"Postgres not reachable ({exc}); run `docker compose up -d db`")
    return url


@pytest.fixture(scope="session")
def migrated_database_url(database_url: str) -> str:
    """Test database migrated to head for the whole session."""
    config = alembic_config(database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return database_url


@pytest.fixture
async def db_engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(migrated_database_url)
    yield engine
    async with engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with make_sessionmaker(db_engine)() as session:
        yield session
