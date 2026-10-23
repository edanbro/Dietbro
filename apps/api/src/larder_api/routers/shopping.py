"""The user's own shopping list items ("bin bags"): kept per user, not per plan, so replans
don't drop them. Plan-made lines live under /plans/{id}/shopping."""

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, select

from larder_api.auth import CurrentUser
from larder_api.db import Session
from larder_api.schemas import ShoppingExtraIn, ShoppingExtraOut, ShoppingExtraPatch
from larder_db.models import ShoppingExtra

router = APIRouter(prefix="/shopping/extras", tags=["shopping"])

MAX_EXTRAS = 100


async def _owned(session: Session, user_id: int, extra_id: int) -> ShoppingExtra:
    extra = await session.scalar(
        select(ShoppingExtra).where(ShoppingExtra.id == extra_id, ShoppingExtra.user_id == user_id)
    )
    if extra is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such item")
    return extra


@router.get("", operation_id="listShoppingExtras")
async def list_extras(user: CurrentUser, session: Session) -> list[ShoppingExtraOut]:
    rows = await session.scalars(
        select(ShoppingExtra).where(ShoppingExtra.user_id == user.id).order_by(ShoppingExtra.id)
    )
    return [ShoppingExtraOut.model_validate(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED, operation_id="addShoppingExtra")
async def add_extra(body: ShoppingExtraIn, user: CurrentUser, session: Session) -> ShoppingExtraOut:
    count = len(
        (
            await session.scalars(select(ShoppingExtra.id).where(ShoppingExtra.user_id == user.id))
        ).all()
    )
    if count >= MAX_EXTRAS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, ["Your list is full: clear some items."])
    extra = ShoppingExtra(user_id=user.id, name=body.name.strip(), checked=False)
    session.add(extra)
    await session.commit()
    return ShoppingExtraOut.model_validate(extra)


@router.patch("/{extra_id}", operation_id="patchShoppingExtra")
async def patch_extra(
    extra_id: int, body: ShoppingExtraPatch, user: CurrentUser, session: Session
) -> ShoppingExtraOut:
    extra = await _owned(session, user.id, extra_id)
    extra.checked = body.checked
    await session.commit()
    return ShoppingExtraOut.model_validate(extra)


@router.delete(
    "/{extra_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteShoppingExtra"
)
async def delete_extra(extra_id: int, user: CurrentUser, session: Session) -> Response:
    await _owned(session, user.id, extra_id)
    await session.execute(delete(ShoppingExtra).where(ShoppingExtra.id == extra_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, operation_id="clearTickedShoppingExtras")
async def clear_ticked(user: CurrentUser, session: Session) -> Response:
    """Remove the items ticked off (bought)."""
    await session.execute(
        delete(ShoppingExtra).where(ShoppingExtra.user_id == user.id, ShoppingExtra.checked)
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
