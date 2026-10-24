"""What the user buys most weeks (GET /shopping/usuals), from their own confirmed receipts."""

from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from test_price_watch import ONION, TESCO_ONIONS, receipt

from larder_api.clock import get_clock
from larder_api.main import app
from larder_db import models as db
from larder_db.engine import make_sessionmaker

Auth = Callable[..., dict[str, str]]
NewUser = Callable[..., Awaitable[int]]

OLIVE_OIL = 171413  # seeded by the `foods` fixture


@pytest.fixture(autouse=True)
def clock() -> Iterator[None]:
    app.dependency_overrides[get_clock] = lambda: lambda: datetime(2026, 10, 14, 12, tzinfo=UTC)
    yield
    app.dependency_overrides.pop(get_clock, None)


@pytest.mark.usefixtures("foods")
async def test_usuals_are_bought_in_three_of_the_last_eight_weeks(
    api: httpx.AsyncClient, auth: Auth, new_user: NewUser, db_engine: AsyncEngine
) -> None:
    me = await new_user("user_a")
    other = await new_user("user_b")
    async with make_sessionmaker(db_engine)() as session:
        session.add(
            db.Food(
                id=TESCO_ONIONS,
                source="off",
                source_id="5000000000007",
                data_type="branded",
                description="Brown onions",
                brand="Tesco",
                generic_food_id=ONION,
            )
        )
        await session.flush()
        session.add_all(
            [
                # Onions in three weeks (one of them the Tesco product): a usual.
                receipt(me, date(2026, 9, 22), ONION, 80),
                receipt(me, date(2026, 9, 30), TESCO_ONIONS, 70),
                receipt(me, date(2026, 10, 13), ONION, 90),
                receipt(me, date(2026, 10, 14), ONION, 90),  # the same week again
                # Olive oil twice in one week, once more long ago and once rejected: not.
                receipt(me, date(2026, 10, 5), OLIVE_OIL, 500),
                receipt(me, date(2026, 10, 6), OLIVE_OIL, 500),
                receipt(me, date(2026, 7, 1), OLIVE_OIL, 500),
                receipt(me, date(2026, 9, 1), OLIVE_OIL, 500, status="rejected"),
                # Someone else's onions never count.
                receipt(other, date(2026, 9, 15), ONION, 80),
            ]
        )
        await session.commit()

    response = await api.get("/shopping/usuals", headers=auth())

    assert response.status_code == 200, response.text
    assert response.json() == [
        {"food_id": ONION, "name": "Onions, raw", "weeks": 3, "last_bought": "2026-10-14"}
    ]
    assert (await api.get("/shopping/usuals", headers=auth("user_b"))).json() == []
