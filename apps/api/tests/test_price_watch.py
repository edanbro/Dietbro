"""Price watch (larder_api.price_watch, GET /insights/prices): per-kg prices from the user's own
receipts, rises against the usual price, and a cheaper product for the same food."""

from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.clock import get_clock
from larder_api.main import app
from larder_api.price_watch import Bought, watch
from larder_db import models as db
from larder_db.engine import make_sessionmaker

Auth = Callable[..., dict[str, str]]
NewUser = Callable[..., Awaitable[int]]

ONION = 170000  # seeded by the `foods` fixture
TESCO_ONIONS = db.LOCAL_ID_START + 7


def bought(on: int, per_kg: int, product: int = 1, item: int = 1, name: str = "Onions") -> Bought:
    return Bought(
        item=item,
        item_name=name,
        product=product,
        label=f"product {product}",
        on=date(2026, 10, on),
        per_kg=per_kg,
    )


def test_a_rise_against_the_usual_price() -> None:
    [item] = watch([bought(1, 800), bought(5, 820), bought(9, 950)])
    assert (item.latest, item.usual, item.change_pct) == (950, 810, 17)
    assert item.rise
    assert [p for _, p in item.history] == [800, 820, 950]


def test_one_earlier_price_is_not_enough_to_call_a_rise() -> None:
    [item] = watch([bought(1, 800), bought(9, 1000)])
    assert item.change_pct == 25
    assert not item.rise


def test_bought_once_is_not_watched() -> None:
    assert watch([bought(1, 800)]) == []


def test_a_misread_price_is_left_out() -> None:
    [item] = watch([bought(1, 800), bought(3, 90), bought(5, 820), bought(9, 840)])
    assert 90 not in [p for _, p in item.history]  # a price on the wrong line, say
    assert item.usual == 810


def test_a_cheaper_product_for_the_same_food() -> None:
    lines = [
        bought(1, 700, product=2),
        bought(3, 720, product=2),
        bought(5, 950),
        bought(9, 1000),
    ]
    [item] = watch(lines)
    assert item.cheaper is not None
    assert (item.cheaper.label, item.cheaper.per_kg) == ("product 2", 710)
    assert item.cheaper.last_bought == date(2026, 10, 3)
    # The cheapest product is the latest: nothing to suggest.
    assert watch([bought(1, 1000, product=2), bought(9, 700)])[0].cheaper is None


def test_rises_come_first() -> None:
    lines = [
        *(bought(d, p, item=1, name="Apples") for d, p in ((1, 300), (2, 300), (3, 300))),
        *(bought(d, p, item=2, name="Butter") for d, p in ((1, 900), (2, 900), (3, 1200))),
    ]
    assert [i.name for i in watch(lines)] == ["Butter", "Apples"]


@pytest.fixture(autouse=True)
def clock() -> Iterator[None]:
    app.dependency_overrides[get_clock] = lambda: lambda: datetime(2026, 10, 14, 12, tzinfo=UTC)
    yield
    app.dependency_overrides.pop(get_clock, None)


def receipt(
    user_id: int,
    on: date,
    food_id: int,
    price: int,
    *,
    approx: bool = False,
    status: str = "accepted",
) -> db.ReceiptUpload:
    return db.ReceiptUpload(
        user_id=user_id,
        source="text",
        status="confirmed",
        purchased_on=on,
        lines=[
            db.ReceiptLine(
                position=0,
                raw_text="ONIONS",
                name="loose onions",
                food_id=food_id,
                grams=500,
                approx=approx,
                price_minor=price,
                status=status,
            )
        ],
    )


@pytest.mark.usefixtures("foods")
async def test_prices_from_your_own_receipts(
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
                receipt(me, date(2026, 10, 1), TESCO_ONIONS, 70),  # 140/kg, the brand
                receipt(me, date(2026, 10, 5), ONION, 80),  # 160/kg
                receipt(me, date(2026, 10, 9), ONION, 100),  # 200/kg
                receipt(me, date(2026, 10, 13), ONION, 110),  # 220/kg, the latest
                receipt(me, date(2026, 10, 12), ONION, 50, approx=True),  # no size printed
                receipt(me, date(2026, 10, 11), ONION, 999, status="rejected"),
                receipt(other, date(2026, 10, 12), ONION, 500),  # someone else's
            ]
        )
        await session.commit()

    response = await api.get("/insights/prices", headers=auth("user_a"))

    assert response.status_code == 200, response.text
    [item] = response.json()["items"]
    assert item["food_id"] == ONION  # the brand counts as the generic food
    assert [p["per_kg_minor"] for p in item["history"]] == [140, 160, 200, 220]
    assert (item["latest_minor"], item["usual_minor"], item["rise"]) == (220, 160, True)
    assert item["cheaper"] == {
        "label": "Tesco Brown onions",
        "per_kg_minor": 140,
        "last_bought": "2026-10-01",
    }
    assert (await api.get("/insights/prices", headers=auth("user_b"))).json()["items"] == []
    assert (await api.get("/insights/prices")).status_code == 401
