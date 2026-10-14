"""Free-tier hosting (larder_api.inline: background work in the API process) and the public
demo account (larder_api.demo)."""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.demo import reset_demo
from larder_api.inline import NO_PHOTOS, InlineWorker
from larder_api.jobs import get_enqueue
from larder_api.main import app
from larder_api.settings import Settings, get_settings
from larder_db import models as db
from larder_db.engine import make_sessionmaker

Auth = Callable[..., dict[str, str]]
NewUser = Callable[..., Awaitable[int]]

DEMO = "user_demo"
INLINE = Settings.model_validate(
    {"worker_in_api": True, "demo_auth_subject": DEMO, "vapid_public_key": None}
)


@pytest.fixture
def inline_settings() -> Iterator[None]:
    app.dependency_overrides[get_settings] = lambda: INLINE
    yield
    app.dependency_overrides.pop(get_settings, None)


# --- demo -------------------------------------------------------------------------------------


@pytest.mark.usefixtures("foods")
async def test_demo_reset_starts_over(db_engine: AsyncEngine) -> None:
    maker = make_sessionmaker(db_engine)
    first = await reset_demo(maker, DEMO, datetime(2026, 10, 14, 3, tzinfo=UTC))
    async with maker() as session:
        session.add(db.ShoppingExtra(user_id=first, name="left by a visitor", checked=False))
        await session.commit()

    second = await reset_demo(maker, DEMO, datetime(2026, 10, 15, 3, tzinfo=UTC))

    async with maker() as session:
        users = (await session.scalars(select(db.User).where(db.User.auth_subject == DEMO))).all()
        extras = await session.scalar(select(func.count(db.ShoppingExtra.id)))
        pantry = (
            await session.scalars(select(db.PantryItem).where(db.PantryItem.user_id == second))
        ).all()
        goals = await session.get(db.Goals, second)
    assert [u.id for u in users] == [second]
    assert (users[0].country, users[0].timezone) == ("IE", "Europe/Dublin")
    assert extras == 0
    assert {p.food_id for p in pantry} >= {170000}  # foods the database has (onions)
    assert goals is not None
    assert (goals.kcal_min, goals.currency) == (1800, "EUR")


@pytest.mark.usefixtures("inline_settings")
async def test_the_demo_account_cant_be_deleted(api: httpx.AsyncClient, auth: Auth) -> None:
    await api.get("/me", headers=auth(DEMO))  # creates the user
    response = await api.delete("/me", headers=auth(DEMO))
    assert response.status_code == 403
    assert (await api.delete("/me", headers=auth("user_a"))).status_code == 204


# --- in-process background work ---------------------------------------------------------------


@pytest.mark.usefixtures("inline_settings")
async def test_photos_are_refused_without_a_worker(api: httpx.AsyncClient, auth: Auth) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    app.dependency_overrides[get_enqueue] = lambda: AsyncMock()
    try:
        response = await api.post(
            "/pantry/receipts/image", files={"file": ("r.png", png, "image/png")}, headers=auth()
        )
    finally:
        app.dependency_overrides.pop(get_enqueue, None)
    assert response.status_code == 503
    assert response.json()["detail"] == NO_PHOTOS


async def test_pasted_receipts_are_read_in_process(
    db_engine: AsyncEngine, new_user: NewUser
) -> None:
    maker = make_sessionmaker(db_engine)
    uid = await new_user("user_a")
    async with maker() as session:
        upload = db.ReceiptUpload(
            user_id=uid,
            source="text",
            status="queued",
            purchased_on=datetime(2026, 10, 14).date(),
            text="MYSTERY GADGET  9.99",
        )
        session.add(upload)
        await session.commit()
        upload_id = upload.id
    worker = InlineWorker(maker, INLINE)

    await worker.enqueue(upload_id)
    await worker.close()  # waits for the read

    async with maker() as session:
        row = await session.get(db.ReceiptUpload, upload_id)
        assert row is not None
        assert row.status in ("ready", "failed")
        assert row.status != "queued"


async def test_ticker_runs_jobs_when_due(db_engine: AsyncEngine) -> None:
    worker = InlineWorker(make_sessionmaker(db_engine), INLINE)
    with (
        patch("larder_api.inline.sweep_stale", AsyncMock(return_value=0)) as sweep,
        patch("larder_api.inline.send_due", AsyncMock(return_value=0)) as remind,
        patch("larder_api.inline.reset_demo", AsyncMock(return_value=1)) as demo,
    ):
        await worker.tick(datetime(2026, 10, 14, 10, 7, tzinfo=UTC))
        assert (sweep.await_count, remind.await_count, demo.await_count) == (0, 0, 0)
        await worker.tick(datetime(2026, 10, 14, 10, 0, tzinfo=UTC))
        assert (sweep.await_count, remind.await_count, demo.await_count) == (1, 1, 0)
        await worker.tick(datetime(2026, 10, 14, 3, 0, tzinfo=UTC))
        assert demo.await_count == 1


async def test_ticker_starts_and_stops(db_engine: AsyncEngine) -> None:
    worker = InlineWorker(make_sessionmaker(db_engine), INLINE)
    worker.start()
    await asyncio.sleep(0)
    await worker.close()
