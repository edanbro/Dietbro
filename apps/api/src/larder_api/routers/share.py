"""Share links: a read-only public page (/s/<token>) for one recipe or a week's plan.

The token is 128 random bits, so links can't be guessed; anyone with one sees only the recipe or
the week's meals (names, photos, kcal), never the person's pantry, goals, weight, allergies or
name. Asking twice for the same thing gives the same link; revoking it stops it working.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from larder_api.auth import CurrentUser
from larder_api.db import Session
from larder_api.routers.recipes import recipe_detail
from larder_api.schemas import (
    RecipeCard,
    SharedDayOut,
    SharedMealOut,
    SharedOut,
    ShareIn,
    ShareOut,
)
from larder_core.meals import SLOT_ORDER, Slot
from larder_db.models import MealPlan, Recipe, ShareLink

router = APIRouter(tags=["share"])

_GONE: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": "no such link, or it was revoked"}
}


def _out(link: ShareLink) -> ShareOut:
    return ShareOut(token=link.token, path=f"/s/{link.token}")


@router.post("/share", operation_id="createShareLink", responses=_GONE)
async def create_share_link(body: ShareIn, user: CurrentUser, session: Session) -> ShareOut:
    """A link to one of the user's recipes (or a catalogue one), or to a week of their plan."""
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
        plan_start=body.start if body.kind == "week" else None,
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


@router.get("/public/share/{token}", operation_id="getShared", responses=_GONE)
async def get_shared(token: str, response: Response, session: Session) -> SharedOut:
    """What a share link shows. No sign-in: the token is the permission."""
    link = await session.scalar(
        select(ShareLink).where(ShareLink.token == token, ShareLink.revoked_at.is_(None))
    )
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "link not found")
    response.headers["Cache-Control"] = "private, max-age=60"
    response.headers["X-Robots-Tag"] = "noindex"
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
