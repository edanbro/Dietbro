"""Pantry CRUD and expiry alerts. Every query is filtered by the signed-in user; other users'
items are 404s. Receipt intake (adding many items from a receipt) is routers/receipts.py."""

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from larder_api.auth import CurrentUser
from larder_api.clock import Clock, get_clock
from larder_api.db import Session
from larder_api.generic_link import ensure_generic
from larder_api.routers.foods import food_portions, summary
from larder_api.schemas import (
    ExpiringItem,
    ExpiringPantry,
    PantryItemIn,
    PantryItemOut,
    PantryItemPatch,
    Problems,
)
from larder_core.quantities import grams_for
from larder_core.regions import local_today
from larder_core.shelf_life import storage_for
from larder_core.units import parse_measure
from larder_db.models import Food, PantryItem, User

router = APIRouter(prefix="/pantry", tags=["pantry"])

_BAD_UNIT: dict[int | str, dict[str, Any]] = {status.HTTP_400_BAD_REQUEST: {"model": Problems}}


async def to_grams(session: AsyncSession, food: Food, quantity: float, unit: str) -> float:
    measure = parse_measure(f"{quantity:g} {unit}")
    portions = await food_portions(session, food)
    grams = grams_for(measure, portions, food.description.lower(), food.category)
    if grams is None or measure.vague:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, [f"can't convert '{unit}' of {food.description} to grams"]
        )
    return grams


def out(item: PantryItem) -> PantryItemOut:
    return PantryItemOut(
        id=item.id,
        food=summary(item.food),
        grams=item.grams,
        quantity=item.quantity,
        unit=item.unit,
        approx=item.approx,
        expires_on=item.expires_on,
        source=item.source,
        created_at=item.created_at,
        storage=storage_for(item.food.description, item.food.category),
    )


async def owned(session: AsyncSession, user: User, item_id: int) -> PantryItem:
    item = await session.scalar(
        select(PantryItem)
        .where(PantryItem.id == item_id, PantryItem.user_id == user.id)
        .options(joinedload(PantryItem.food))
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pantry item not found")
    return item


@router.get("", operation_id="listPantry")
async def list_items(user: CurrentUser, session: Session) -> list[PantryItemOut]:
    """Soonest-expiring first; items without a date last. Used-up items (0 g left after meals
    were marked eaten) are kept for undo but not listed."""
    rows = await session.scalars(
        select(PantryItem)
        .where(PantryItem.user_id == user.id, PantryItem.grams > 0)
        .options(joinedload(PantryItem.food))
        .order_by(PantryItem.expires_on.asc().nulls_last(), PantryItem.id)
    )
    return [out(i) for i in rows]


EXPIRING_DAYS = 3  # "expiring soon": use-by before today + 3 days (the planner's SOON_DAYS)


async def expiring_count(session: AsyncSession, user: User, today: date) -> int:
    """Items with something left that are expired or expire within EXPIRING_DAYS."""
    count = await session.scalar(
        select(func.count(PantryItem.id)).where(
            PantryItem.user_id == user.id,
            PantryItem.grams > 0,
            PantryItem.expires_on < today + timedelta(days=EXPIRING_DAYS),
        )
    )
    return count or 0


@router.get("/expiring", operation_id="listExpiringPantry")
async def list_expiring(
    user: CurrentUser,
    session: Session,
    clock: Annotated[Clock, Depends(get_clock)],
    days: Annotated[int, Query(ge=0, le=60)] = EXPIRING_DAYS,
    today: Annotated[
        date | None, Query(description="The user's local date (default: today in their time zone)")
    ] = None,
) -> ExpiringPantry:
    """Expiry alerts: items with something left whose use-by date is before `today` + `days`
    (so days=3 means today, tomorrow and the day after), expired ones included, soonest
    first."""
    today = today or local_today(user.timezone, clock())
    rows = await session.scalars(
        select(PantryItem)
        .where(
            PantryItem.user_id == user.id,
            PantryItem.grams > 0,
            PantryItem.expires_on < today + timedelta(days=days),
        )
        .options(joinedload(PantryItem.food))
        .order_by(PantryItem.expires_on, PantryItem.id)
    )
    items: list[ExpiringItem] = []
    for row in rows:
        assert row.expires_on is not None
        left = (row.expires_on - today).days
        items.append(ExpiringItem(**out(row).model_dump(), days_left=left))
    return ExpiringPantry(
        today=today, days=days, expired=sum(i.days_left < 0 for i in items), items=items
    )


@router.post(
    "", status_code=status.HTTP_201_CREATED, operation_id="addPantryItem", responses=_BAD_UNIT
)
async def add_item(body: PantryItemIn, user: CurrentUser, session: Session) -> PantryItemOut:
    food = await session.get(Food, body.food_id)
    if food is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "food not found")
    await ensure_generic(session, food)  # a product counts as its generic food when planning
    item = PantryItem(
        user_id=user.id,
        food_id=food.id,
        grams=await to_grams(session, food, body.quantity, body.unit),
        quantity=body.quantity,
        unit=body.unit,
        approx=body.approx,
        expires_on=body.expires_on,
        source="manual",
    )
    session.add(item)
    await session.commit()
    return out(await owned(session, user, item.id))


@router.patch("/{item_id}", operation_id="updatePantryItem", responses=_BAD_UNIT)
async def update_item(
    item_id: int, body: PantryItemPatch, user: CurrentUser, session: Session
) -> PantryItemOut:
    item = await owned(session, user, item_id)
    changes = body.model_dump(exclude_unset=True)
    if "quantity" in changes or "unit" in changes:
        item.quantity = body.quantity or item.quantity
        item.unit = body.unit or item.unit
        item.grams = await to_grams(session, item.food, item.quantity, item.unit)
    if "approx" in changes and body.approx is not None:
        item.approx = body.approx
    if "expires_on" in changes:
        item.expires_on = body.expires_on
    await session.commit()
    return out(await owned(session, user, item_id))


@router.delete(
    "/{item_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deletePantryItem"
)
async def delete_item(item_id: int, user: CurrentUser, session: Session) -> Response:
    await session.delete(await owned(session, user, item_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
