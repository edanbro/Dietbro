"""Grocery spending from confirmed receipts, week by week (GET /insights/spending). It is
Wednesday 14 Oct 2026, so this week starts Monday 12 Oct."""

from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.clock import get_clock
from larder_api.main import app
from larder_db import models as db
from larder_db.engine import make_sessionmaker

Auth = Callable[..., dict[str, str]]
NewUser = Callable[..., Awaitable[int]]

ONION = 170000  # seeded by the `foods` fixture
TODAY = date(2026, 10, 14)
MON = date(2026, 10, 12)


@pytest.fixture(autouse=True)
def clock() -> Iterator[None]:
    app.dependency_overrides[get_clock] = lambda: lambda: datetime(2026, 10, 14, 12, tzinfo=UTC)
    yield
    app.dependency_overrides.pop(get_clock, None)


def upload(
    user_id: int,
    on: date,
    lines: list[tuple[int | None, int]],
    *,
    status: str = "confirmed",
    line_status: str = "accepted",
) -> db.ReceiptUpload:
    return db.ReceiptUpload(
        user_id=user_id,
        source="text",
        status=status,
        purchased_on=on,
        lines=[
            db.ReceiptLine(
                position=i,
                raw_text="ITEM",
                name="item",
                food_id=food_id,
                grams=500,
                price_minor=price,
                status=line_status,
            )
            for i, (food_id, price) in enumerate(lines)
        ],
    )


def plan(user_id: int, start: date, version: int, cost: int) -> db.MealPlan:
    return db.MealPlan(
        user_id=user_id,
        start_date=start,
        days=7,
        version=version,
        currency="EUR",
        planner="greedy",
        status="optimal",
        solve_ms=1,
        stats={"cost_minor": cost},
    )


@pytest.mark.usefixtures("foods")
async def test_weekly_spending_beside_the_plans(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser, db_engine: AsyncEngine
) -> None:
    me, other = await new_user("user_a"), await new_user("user_b")
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            [
                upload(me, TODAY, [(ONION, 150), (None, 250)]),  # this week; one line unmatched
                upload(me, MON - timedelta(days=1), [(ONION, 300)]),  # Sunday: last week
                upload(me, TODAY, [(ONION, 999)], status="ready"),  # not confirmed
                upload(me, TODAY, [(ONION, 999)], line_status="rejected"),
                upload(me, MON - timedelta(weeks=5), [(ONION, 999)]),  # outside 4 weeks
                upload(other, TODAY, [(ONION, 999)]),  # someone else's
                plan(me, MON, 1, 4000),
                plan(me, MON, 2, 4500),  # the latest version counts
                plan(other, MON, 1, 9999),
            ]
        )
        await session.commit()

    response = await api.get("/insights/spending?weeks=4", headers=auth("user_a"))

    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert [w["start"] for w in body["weeks"]] == [
        (MON - timedelta(weeks=n)).isoformat() for n in (3, 2, 1, 0)
    ]
    assert [w["spent_minor"] for w in body["weeks"]] == [0, 0, 300, 400]
    assert [w["planned_minor"] for w in body["weeks"]] == [None, None, None, 4500]
    assert body["unmatched_minor"] == 250
    assert [c["spent_minor"] for c in body["categories"]] == [450]


async def test_spending_needs_sign_in(api: httpx.AsyncClient) -> None:
    assert (await api.get("/insights/spending")).status_code == 401
