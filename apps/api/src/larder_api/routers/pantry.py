"""Pantry CRUD. Every query is filtered by the signed-in user; other users' items are 404s."""

from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from larder_api.auth import CurrentUser
from larder_api.db import Session
from larder_api.routers.foods import load_portions, summary
from larder_api.schemas import PantryItemIn, PantryItemOut, PantryItemPatch, Problems
from larder_core.quantities import grams_for
from larder_core.units import parse_measure
from larder_db.models import Food, PantryItem, User

router = APIRouter(prefix="/pantry", tags=["pantry"])

_BAD_UNIT: dict[int | str, dict[str, Any]] = {status.HTTP_400_BAD_REQUEST: {"model": Problems}}


async def to_grams(session: AsyncSession, food: Food, quantity: float, unit: str) -> float:
    measure = parse_measure(f"{quantity:g} {unit}")
    portions = await load_portions(session, food.id)
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
    """Soonest-expiring first; items without a date last."""
    rows = await session.scalars(
        select(PantryItem)
        .where(PantryItem.user_id == user.id)
        .options(joinedload(PantryItem.food))
        .order_by(PantryItem.expires_on.asc().nulls_last(), PantryItem.id)
    )
    return [out(i) for i in rows]


@router.post(
    "", status_code=status.HTTP_201_CREATED, operation_id="addPantryItem", responses=_BAD_UNIT
)
async def add_item(body: PantryItemIn, user: CurrentUser, session: Session) -> PantryItemOut:
    food = await session.get(Food, body.food_id)
    if food is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "food not found")
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
