"""Prices learned from the user's own confirmed receipts (larder_api.prices)."""

from collections.abc import Awaitable, Callable
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.prices import learned_price, price_with_receipts, receipt_prices
from larder_db import models as db
from larder_db.engine import make_sessionmaker

NewUser = Callable[..., Awaitable[int]]

ONION = 170000  # seeded by the `foods` fixture
TODAY = date(2026, 10, 14)


def test_learned_price_is_the_median_of_believable_prices() -> None:
    assert learned_price(100, [120, 90, 110]) == 110
    assert learned_price(100, [120, 5_000]) == 120  # 50x the estimate: misread
    assert learned_price(100, [10]) is None  # a tenth: misread, keep the estimate
    assert learned_price(0, [10]) == 10  # nothing to compare with


def test_price_with_receipts_falls_back_to_the_estimate() -> None:
    assert price_with_receipts(100, ONION, {ONION: (130,)}) == 130
    assert price_with_receipts(100, ONION, {}) == 100


def _upload(
    user_id: int,
    lines: list[tuple[int, float, int]],
    *,
    days_ago: int = 1,
    status: str = "confirmed",
    line_status: str = "accepted",
    approx: bool = False,
) -> db.ReceiptUpload:
    return db.ReceiptUpload(
        user_id=user_id,
        source="text",
        status=status,
        purchased_on=TODAY - timedelta(days=days_ago),
        lines=[
            db.ReceiptLine(
                position=i,
                raw_text="ONIONS",
                name="onion",
                food_id=food_id,
                grams=grams,
                approx=approx,
                price_minor=price,
                status=line_status,
            )
            for i, (food_id, grams, price) in enumerate(lines)
        ],
    )


@pytest.mark.usefixtures("foods")
async def test_receipt_prices_per_kg_newest_first(
    db_engine: AsyncEngine, new_user: NewUser
) -> None:
    me, other = await new_user("user_a"), await new_user("user_b")
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(
            [
                _upload(me, [(ONION, 1000, 95)], days_ago=10),
                _upload(me, [(ONION, 500, 60)], days_ago=2),  # 120 per kg
                _upload(me, [(ONION, 1000, 300)], days_ago=200),  # too old
                _upload(me, [(ONION, 1000, 400)], status="ready"),  # not confirmed
                _upload(me, [(ONION, 1000, 500)], line_status="rejected"),
                _upload(me, [(ONION, 1000, 600)], approx=True),  # size not printed
                _upload(other, [(ONION, 1000, 700)]),  # someone else's
            ]
        )
        await session.commit()

        paid = await receipt_prices(session, me, TODAY)

    assert paid == {ONION: (120, 95)}


@pytest.mark.usefixtures("foods")
async def test_receipt_prices_keep_the_latest_five(
    db_engine: AsyncEngine, new_user: NewUser
) -> None:
    me = await new_user()
    async with make_sessionmaker(db_engine)() as session:
        session.add_all(_upload(me, [(ONION, 1000, 100 + d)], days_ago=d) for d in range(1, 8))
        await session.commit()

        paid = await receipt_prices(session, me, TODAY)

    assert paid[ONION] == (101, 102, 103, 104, 105)
