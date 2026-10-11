"""Recipe catalogue (public data: TheMealDB + curated recipes) and the signed-in user's own
generated recipes, which nobody else can see (docs/DESIGN.md §9.4)."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_api.auth import AuthError, TokenVerifier
from larder_api.db import Session
from larder_api.schemas import MacrosOut, RecipeDetail, RecipeIngredientOut
from larder_core.meals import SLOT_ORDER
from larder_db.models import Food, Recipe, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recipes", tags=["recipes"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": "no such recipe (or another user's)"}
}
_bearer = HTTPBearer(auto_error=False)


def get_optional_verifier(request: Request) -> TokenVerifier | None:
    """The token verifier, or None when sign-in isn't configured (then callers are anonymous)."""
    return getattr(request.app.state, "verifier", None)


async def viewer_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier | None, Depends(get_optional_verifier)],
    session: Session,
) -> int | None:
    """The signed-in caller's user id; None when anonymous. A bad token is 401, as elsewhere."""
    if credentials is None:
        return None
    if verifier is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "authentication is not configured")
    try:
        subject = await verifier.subject(credentials.credentials)
    except AuthError as exc:
        logger.info("rejected token: %s", exc)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "not signed in", headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    return await session.scalar(select(User.id).where(User.auth_subject == subject))


Viewer = Annotated[int | None, Depends(viewer_id)]


@router.get("/{recipe_id}", operation_id="getRecipe", responses=_NOT_FOUND)
async def get_recipe(recipe_id: int, session: Session, viewer: Viewer) -> RecipeDetail:
    """A recipe with allergens and suitable diets derived the same way the planner derives them
    (never TheMealDB's category, which isn't a diet claim). Signing in is optional: a generated
    recipe is only found by its owner."""
    visible = (
        Recipe.owner_user_id.is_(None)
        if viewer is None
        else or_(Recipe.owner_user_id.is_(None), Recipe.owner_user_id == viewer)
    )
    recipe = await session.scalar(
        select(Recipe)
        .where(Recipe.id == recipe_id, visible)
        .options(selectinload(Recipe.ingredients))
    )
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
    food_ids = {i.food_id for i in recipe.ingredients if i.food_id is not None}
    foods = {f.id: f for f in await session.scalars(select(Food).where(Food.id.in_(food_ids)))}
    info = {fid: planning.food_info(f) for fid, f in foods.items()}
    facts = planning.recipe_facts(recipe, foods, info)
    per_serving = (
        MacrosOut(
            kcal=facts.per_portion.kcal * 2,
            protein_g=facts.per_portion.protein_g * 2,
            fat_g=facts.per_portion.fat_g * 2,
            carbs_g=facts.per_portion.carbs_g * 2,
        )
        if facts.per_portion
        else None
    )
    return RecipeDetail(
        id=recipe.id,
        name=recipe.name,
        category=recipe.category,
        cuisine=recipe.cuisine,
        image_url=recipe.image_url,
        instructions=recipe.instructions,
        generated=recipe.owner_user_id is not None,
        source=recipe.source,
        source_url=recipe.source_url,
        servings=recipe.servings,
        servings_estimated=recipe.servings_estimated,
        per_serving=per_serving,
        meal_types=sorted(facts.slots, key=SLOT_ORDER.index),
        allergens=sorted(facts.tags.allergens),
        allergens_complete=facts.tags.complete,
        suitable_for=facts.tags.suitable_for(),
        ingredients=[
            RecipeIngredientOut(
                name=i.raw_name,
                measure=i.raw_measure,
                food_id=i.food_id,
                food_name=foods[i.food_id].description if i.food_id is not None else None,
                grams=i.grams,
            )
            for i in sorted(recipe.ingredients, key=lambda i: i.position)
        ],
    )
