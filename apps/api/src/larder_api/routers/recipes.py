"""Recipe catalogue (public data: TheMealDB + curated recipes) and the signed-in user's own
generated recipes, which nobody else can see (docs/DESIGN.md §9.4)."""

import logging
from collections.abc import Mapping
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_api.auth import AuthError, CurrentUser, TokenVerifier
from larder_api.chat.search import query_words, rank_recipes, viewer_of
from larder_api.db import Session, get_sessionmaker
from larder_api.routers.foods import FRUIT_VEG_CATEGORIES
from larder_api.routers.plans import get_catalog_cache
from larder_api.schemas import (
    MacrosOut,
    NutritionGrade,
    RecipeDetail,
    RecipeFeedbackIn,
    RecipeIngredientOut,
    RecipeListItem,
    RecipeListOut,
    RecipeVerdict,
)
from larder_core.meals import SLOT_ORDER, Slot
from larder_core.nutrigrade import NutriInput, grade
from larder_db.models import Food, Preferences, Recipe, User

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

_SETUP = "Tell us about your allergies and diet first, so we only show recipes safe for you."


@router.get("", operation_id="listRecipes", responses={409: {"description": "setup incomplete"}})
async def list_recipes(
    user: CurrentUser,
    session: Session,
    cache: Annotated[planning.CatalogCache, Depends(get_catalog_cache)],
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    q: Annotated[str, Query(max_length=100)] = "",
    slot: Slot | None = None,
    favourites: bool = False,
    limit: Annotated[int, Query(ge=1, le=60)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RecipeListOut:
    """Plannable recipes safe for the user (allergies, diet, avoided foods; never ones they
    blocked), matching `q` if given, ranked like the chat's search: match, then preference
    (favourites first), then pantry use."""
    viewer = await viewer_of(session, user.id)
    if viewer is None:
        raise HTTPException(status.HTTP_409_CONFLICT, [_SETUP])
    words = query_words(q)
    if q.strip() and not words:
        return RecipeListOut(items=[], total=0)
    pool = (await cache.get(sessionmaker)).merged(
        await planning.load_private_recipes(session, user.id)
    )
    hits = rank_recipes(pool, viewer, words, slot, favourites_only=favourites)
    return RecipeListOut(
        items=[
            RecipeListItem(
                id=h.id,
                name=h.name,
                category=h.category,
                cuisine=h.cuisine,
                image_url=h.image_url,
                slots=list(h.slots),
                kcal_per_serving=h.kcal_per_serving,
                protein_g_per_serving=h.protein_g_per_serving,
                uses_pantry=list(h.uses_pantry),
                favourite=h.favourite,
            )
            for h in hits[offset : offset + limit]
        ],
        total=len(hits),
    )


@router.put(
    "/{recipe_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="putRecipeFeedback",
    responses=_NOT_FOUND | {409: {"description": "setup incomplete"}},
)
async def put_feedback(
    recipe_id: int, body: RecipeFeedbackIn, user: CurrentUser, session: Session
) -> Response:
    """Favourite a recipe (planned more often) or never plan it again; replaces any earlier
    verdict. Plans already made keep it until the next plan or replan."""
    prefs = await _feedback_target(session, user.id, recipe_id)
    favourites = [r for r in prefs.favourite_recipe_ids or [] if r != recipe_id]
    blocked = [r for r in prefs.blocked_recipe_ids or [] if r != recipe_id]
    (favourites if body.verdict == "favourite" else blocked).append(recipe_id)
    prefs.favourite_recipe_ids, prefs.blocked_recipe_ids = favourites, blocked
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{recipe_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteRecipeFeedback",
    responses=_NOT_FOUND | {409: {"description": "setup incomplete"}},
)
async def delete_feedback(recipe_id: int, user: CurrentUser, session: Session) -> Response:
    prefs = await _feedback_target(session, user.id, recipe_id)
    prefs.favourite_recipe_ids = [r for r in prefs.favourite_recipe_ids or [] if r != recipe_id]
    prefs.blocked_recipe_ids = [r for r in prefs.blocked_recipe_ids or [] if r != recipe_id]
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _feedback_target(session: Session, user_id: int, recipe_id: int) -> Preferences:
    visible = await session.scalar(
        select(Recipe.id).where(
            Recipe.id == recipe_id,
            or_(Recipe.owner_user_id.is_(None), Recipe.owner_user_id == user_id),
        )
    )
    if visible is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
    prefs = await session.get(Preferences, user_id)
    if prefs is None:
        raise HTTPException(status.HTTP_409_CONFLICT, [_SETUP])
    return prefs


def verdict_of(prefs: Preferences | None, recipe_id: int) -> RecipeVerdict | None:
    if prefs is None:
        return None
    if recipe_id in (prefs.favourite_recipe_ids or ()):
        return "favourite"
    if recipe_id in (prefs.blocked_recipe_ids or ()):
        return "never"
    return None


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
            **planning.extra_nutrients(recipe, 1),
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
        grade=recipe_grade(recipe, foods),
        feedback=verdict_of(await session.get(Preferences, viewer), recipe.id) if viewer else None,
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


def recipe_grade(recipe: Recipe, foods: Mapping[int, Food]) -> NutritionGrade | None:
    """Nutri-Score method per 100 g of the dish: the per-serving columns over the serving's
    weight, fruit/veg/legumes from the ingredients' food groups."""
    if not recipe.nutrition_complete or not recipe.servings:
        return None
    weighed = [(i.grams or 0.0, foods.get(i.food_id or 0)) for i in recipe.ingredients]
    total = sum(g for g, _ in weighed)
    if total <= 0:
        return None
    fruit_veg = sum(g for g, f in weighed if f is not None and f.category in FRUIT_VEG_CATEGORIES)
    per_100g = 100 * recipe.servings / total  # columns are per serving

    def scaled(value: float | None) -> float | None:
        return None if value is None else value * per_100g

    found = grade(
        NutriInput(
            kcal=scaled(recipe.kcal),
            sugars_g=scaled(recipe.sugars_g),
            sat_fat_g=scaled(recipe.sat_fat_g),
            sodium_mg=scaled(recipe.sodium_mg),
            protein_g=scaled(recipe.protein_g),
            fiber_g=scaled(recipe.fiber_g),
            fruit_veg_pct=100 * fruit_veg / total,
        )
    )
    return cast(NutritionGrade | None, found)
