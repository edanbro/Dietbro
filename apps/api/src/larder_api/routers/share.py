"""Share links: a public page (/s/<token>) for one recipe, a week's plan or a week's shopping
list.

The token is 128 random bits, so links can't be guessed; anyone with one sees only the recipe,
the week's meals (names, photos, kcal) or the shopping list (no prices), never the person's
pantry, goals, weight, allergies or name. Recipes and weeks are read-only; a shopping list can
be ticked off through its link, so a household can shop together without accounts. Asking twice
for the same thing gives the same link; revoking it stops it working.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_api.auth import CurrentUser
from larder_api.db import Session
from larder_api.ratelimit import per_ip, per_path, per_user
from larder_api.routers.plans import shopping_out
from larder_api.routers.recipes import recipe_detail
from larder_api.schemas import (
    RecipeCard,
    SharedDayOut,
    SharedExtraOut,
    SharedItemOut,
    SharedListOut,
    SharedMealOut,
    SharedOut,
    SharedTickIn,
    ShareIn,
    ShareOut,
)
from larder_core.meals import SLOT_ORDER, Slot
from larder_db.models import MealPlan, Recipe, ShareLink, ShoppingExtra

router = APIRouter(tags=["share"])

_GONE: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": "no such link, or it was revoked"}
}


def _out(link: ShareLink) -> ShareOut:
    return ShareOut(token=link.token, path=f"/s/{link.token}")


@router.post(
    "/share",
    operation_id="createShareLink",
    responses=_GONE,
    dependencies=[Depends(per_user("share_create"))],
)
async def create_share_link(body: ShareIn, user: CurrentUser, session: Session) -> ShareOut:
    """A link to one of the user's recipes (or a catalogue one), or to a week of their plan or
    its shopping list."""
    if body.kind == "recipe":
        if body.recipe_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "recipe_id is required")
        visible = await session.scalar(
            select(Recipe.id).where(
                Recipe.id == body.recipe_id,
                or_(Recipe.owner_user_id.is_(None), Recipe.owner_user_id == user.id),
            )
        )
        if visible is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
        target = ShareLink.recipe_id == body.recipe_id
    else:
        if body.start is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "start is required")
        planned = await session.scalar(
            select(MealPlan.id)
            .where(MealPlan.user_id == user.id, MealPlan.start_date == body.start)
            .limit(1)
        )
        if planned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no plan starts that day")
        target = ShareLink.plan_start == body.start
    existing = await session.scalar(
        select(ShareLink).where(
            ShareLink.user_id == user.id,
            ShareLink.kind == body.kind,
            target,
            ShareLink.revoked_at.is_(None),
        )
    )
    if existing is not None:
        return _out(existing)
    link = ShareLink(
        token=secrets.token_urlsafe(16),
        user_id=user.id,
        kind=body.kind,
        recipe_id=body.recipe_id if body.kind == "recipe" else None,
        plan_start=body.start if body.kind != "recipe" else None,
    )
    session.add(link)
    await session.commit()
    return _out(link)


@router.delete(
    "/share/{token}",
    operation_id="revokeShareLink",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_GONE,
)
async def revoke_share_link(token: str, user: CurrentUser, session: Session) -> Response:
    link = await session.scalar(
        select(ShareLink).where(
            ShareLink.token == token,
            ShareLink.user_id == user.id,
            ShareLink.revoked_at.is_(None),
        )
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "link not found")
    link.revoked_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/public/share/{token}",
    operation_id="getShared",
    responses=_GONE,
    dependencies=[
        Depends(per_path("share_view", "token")),
        Depends(per_ip("share_view_ip")),
    ],
)
async def get_shared(token: str, response: Response, session: Session) -> SharedOut:
    """What a share link shows. No sign-in: the token is the permission."""
    link = await _live_link(session, token)
    # A shopping list changes as people tick it; the others don't change much.
    response.headers["Cache-Control"] = "no-store" if link.kind == "list" else "private, max-age=60"
    response.headers["X-Robots-Tag"] = "noindex"
    if link.kind == "list":
        return SharedOut(kind="list", shopping=await _shared_list(session, link))
    if link.kind == "recipe":
        recipe = await session.scalar(
            select(Recipe)
            .where(Recipe.id == link.recipe_id)
            .options(selectinload(Recipe.ingredients))
        )
        if recipe is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "link not found")
        return SharedOut(kind="recipe", recipe=await recipe_detail(session, recipe, None))

    plan = await session.scalar(
        select(MealPlan)
        .where(MealPlan.user_id == link.user_id, MealPlan.start_date == link.plan_start)
        .order_by(MealPlan.version.desc())
        .limit(1)
        .options(selectinload(MealPlan.meals))
    )
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "link not found")
    rows = {
        r.id: r
        for r in await session.scalars(
            select(Recipe).where(Recipe.id.in_({m.recipe_id for m in plan.meals}))
        )
    }
    recipes = {rid: RecipeCard.model_validate(r, from_attributes=True) for rid, r in rows.items()}
    days: list[SharedDayOut] = []
    for day in range(plan.days):
        meals = sorted(
            (m for m in plan.meals if m.day == day and m.recipe_id in recipes),
            key=lambda m: SLOT_ORDER.index(Slot(m.slot)),
        )
        days.append(
            SharedDayOut(
                date=plan.start_date + timedelta(days=day),
                meals=[
                    SharedMealOut(
                        slot=Slot(m.slot),
                        recipe=RecipeCard.model_validate(
                            recipes[m.recipe_id], from_attributes=True
                        ),
                        kcal=m.kcal,
                    )
                    for m in meals
                ],
            )
        )
    return SharedOut(kind="week", days=days)


async def _live_link(session: AsyncSession, token: str, kind: str | None = None) -> ShareLink:
    """The link with this token, not revoked (and of `kind`, if given); else 404."""
    link = await session.scalar(
        select(ShareLink).where(ShareLink.token == token, ShareLink.revoked_at.is_(None))
    )
    if link is None or (kind is not None and link.kind != kind):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "link not found")
    return link


async def _list_plan(session: AsyncSession, link: ShareLink) -> MealPlan:
    """The newest version of the shared week's plan, its shopping list loaded."""
    plan = await session.scalar(
        select(MealPlan)
        .where(MealPlan.user_id == link.user_id, MealPlan.start_date == link.plan_start)
        .order_by(MealPlan.version.desc())
        .limit(1)
        .options(selectinload(MealPlan.shopping))
    )
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "link not found")
    return plan


async def _shared_list(session: AsyncSession, link: ShareLink) -> SharedListOut:
    full = await shopping_out(session, await _list_plan(session, link))
    extras = await session.scalars(
        select(ShoppingExtra)
        .where(ShoppingExtra.user_id == link.user_id)
        .order_by(ShoppingExtra.id)
    )
    assert link.plan_start is not None  # a list link always has its week (ck_share_links_target)
    return SharedListOut(
        start=link.plan_start,
        household=full.household,
        items=[
            SharedItemOut(
                food_id=i.food_id,
                name=i.name,
                category=i.category,
                grams=i.grams,
                approx_units=i.approx_units,
                checked=i.checked,
                staple=i.staple,
            )
            for i in full.items
        ],
        extras=[SharedExtraOut(id=e.id, name=e.name, checked=e.checked) for e in extras],
    )


_TICK = [Depends(per_path("share_tick", "token")), Depends(per_ip("share_tick_ip"))]


@router.patch(
    "/public/share/{token}/items/{food_id}",
    operation_id="tickSharedItem",
    responses=_GONE,
    dependencies=_TICK,
)
async def tick_shared_item(
    token: str, food_id: int, body: SharedTickIn, response: Response, session: Session
) -> SharedListOut:
    """Tick (or untick) a line of a shared shopping list; the whole list as it is now."""
    link = await _live_link(session, token, "list")
    plan = await _list_plan(session, link)
    line = next((s for s in plan.shopping if s.food_id == food_id), None)
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not on this list")
    line.checked = body.checked
    await session.commit()
    response.headers["Cache-Control"] = "no-store"
    return await _shared_list(session, link)


@router.patch(
    "/public/share/{token}/extras/{extra_id}",
    operation_id="tickSharedExtra",
    responses=_GONE,
    dependencies=_TICK,
)
async def tick_shared_extra(
    token: str, extra_id: int, body: SharedTickIn, response: Response, session: Session
) -> SharedListOut:
    """Tick (or untick) one of the owner's own items on a shared shopping list."""
    link = await _live_link(session, token, "list")
    extra = await session.scalar(
        select(ShoppingExtra).where(
            ShoppingExtra.id == extra_id, ShoppingExtra.user_id == link.user_id
        )
    )
    if extra is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not on this list")
    extra.checked = body.checked
    await session.commit()
    response.headers["Cache-Control"] = "no-store"
    return await _shared_list(session, link)
