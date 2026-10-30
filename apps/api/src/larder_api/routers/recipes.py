"""Recipe catalogue (public data: TheMealDB + curated recipes) and the signed-in user's own
generated recipes, which nobody else can see (docs/DESIGN.md §9.4)."""

import logging
from collections.abc import Mapping
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from larder_api import planning, recipe_import, replans
from larder_api.auth import AuthError, CurrentUser, TokenVerifier
from larder_api.changes.create import create_recipe
from larder_api.changes.search import query_words, rank_recipes, time_limit, viewer_of
from larder_api.clock import Clock, get_clock
from larder_api.db import Session, get_sessionmaker
from larder_api.ratelimit import per_user
from larder_api.routers.foods import FRUIT_VEG_CATEGORIES
from larder_api.routers.plans import get_catalog_cache, get_replan_planner
from larder_api.schemas import (
    ImportDraft,
    ImportIngredient,
    ImportReadIn,
    ImportResultOut,
    MacrosOut,
    NutritionGrade,
    RecipeDeletedOut,
    RecipeDetail,
    RecipeFeedbackIn,
    RecipeIngredientOut,
    RecipeListItem,
    RecipeListOut,
    RecipeNoteIn,
    RecipeNoteOut,
    RecipeVerdict,
)
from larder_api.settings import Settings, get_settings
from larder_core.meals import SLOT_ORDER, Slot
from larder_core.nutrigrade import NutriInput, grade
from larder_core.recipe_import import ImportedRecipe, split_line
from larder_core.regions import local_today
from larder_db.models import (
    Food,
    PantryItem,
    PlanMeal,
    Preferences,
    Recipe,
    RecipeNote,
    User,
)
from larder_llm.schemas import CreateRecipeInput, DraftIngredient

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
    max_minutes: Annotated[int | None, Query(ge=5, le=240)] = None,
    pantry: bool = False,
    cheapest: bool = False,
    limit: Annotated[int, Query(ge=1, le=60)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RecipeListOut:
    """Plannable recipes safe for the user (allergies, diet, avoided foods; never ones they
    blocked), matching `q` if given, ranked like the swap search: match, then preference
    (favourites first), then pantry use. `pantry`: what can be cooked from the pantry, fewest
    foods still to get first, each with those foods (`missing`). `cheapest`: the lowest cost a
    serving first (in the user's prices), those without a price last."""
    viewer = await viewer_of(session, user.id)
    if viewer is None:
        raise HTTPException(status.HTTP_409_CONFLICT, [_SETUP])
    words, quick = time_limit(query_words(q))
    if q.strip() and not (words or quick):
        return RecipeListOut(items=[], total=0)
    if quick is not None:
        max_minutes = min(max_minutes or quick, quick)
    pool = (await cache.get(sessionmaker)).merged(
        await planning.load_private_recipes(session, user.id)
    )
    pricer = await planning.pricer_for(session, user.id)
    hits = rank_recipes(
        pool,
        viewer,
        words,
        slot,
        favourites_only=favourites,
        max_minutes=max_minutes,
        from_pantry=pantry,
        pricer=pricer,
    )
    if cheapest:  # stable: ties keep the ranking above
        hits.sort(key=lambda h: (h.cost_per_serving is None, h.cost_per_serving or 0))
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
                minutes=h.minutes,
                missing=None if h.missing is None else list(h.missing),
                cost_per_serving=h.cost_per_serving,
            )
            for h in hits[offset : offset + limit]
        ],
        total=len(hits),
        currency=pricer.currency,
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


@router.delete("/{recipe_id}", operation_id="deleteRecipe", responses=_NOT_FOUND)
async def delete_recipe(recipe_id: int, user: CurrentUser, session: Session) -> RecipeDeletedOut:
    """Delete a recipe of the user's own (imported, typed in or edited). One their plans have
    can't go (the plans keep it): it is hidden instead, never shown in browsing or planned
    again. Catalogue recipes can't be deleted ("never again" hides them)."""
    recipe = await session.scalar(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.owner_user_id == user.id)
    )
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, ["That isn't one of your recipes."])
    planned = await session.scalar(select(PlanMeal.id).where(PlanMeal.recipe_id == recipe_id))
    prefs = await session.get(Preferences, user.id)
    if prefs is not None:
        prefs.favourite_recipe_ids = [r for r in prefs.favourite_recipe_ids or [] if r != recipe_id]
        blocked = [r for r in prefs.blocked_recipe_ids or [] if r != recipe_id]
        prefs.blocked_recipe_ids = [*blocked, recipe_id] if planned is not None else blocked
    if planned is None:
        await session.delete(recipe)
    elif prefs is None:
        raise HTTPException(status.HTTP_409_CONFLICT, [_SETUP])
    await session.commit()
    return RecipeDeletedOut(hidden=planned is not None)


async def _visible(session: Session, user_id: int, recipe_id: int) -> None:
    """404 unless the recipe is in the catalogue or the user's own."""
    found = await session.scalar(
        select(Recipe.id).where(
            Recipe.id == recipe_id,
            or_(Recipe.owner_user_id.is_(None), Recipe.owner_user_id == user_id),
        )
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")


async def _feedback_target(session: Session, user_id: int, recipe_id: int) -> Preferences:
    await _visible(session, user_id, recipe_id)
    prefs = await session.get(Preferences, user_id)
    if prefs is None:
        raise HTTPException(status.HTTP_409_CONFLICT, [_SETUP])
    return prefs


@router.put("/{recipe_id}/note", operation_id="putRecipeNote", responses=_NOT_FOUND)
async def put_note(
    recipe_id: int, body: RecipeNoteIn, user: CurrentUser, session: Session
) -> RecipeNoteOut | None:
    """The user's own note and 1-5 rating on a recipe; both empty removes it (null). Private:
    never on a share link, and it doesn't steer the planner."""
    await _visible(session, user.id, recipe_id)
    text = (body.note or "").strip() or None
    row = await session.get(RecipeNote, (user.id, recipe_id))
    if text is None and body.rating is None:
        if row is not None:
            await session.delete(row)
            await session.commit()
        return None
    if row is None:
        row = RecipeNote(user_id=user.id, recipe_id=recipe_id)
        session.add(row)
    row.note, row.rating = text, body.rating
    await session.commit()
    await session.refresh(row)
    return note_out(row)


@router.delete(
    "/{recipe_id}/note",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteRecipeNote",
    responses=_NOT_FOUND,
)
async def delete_note(recipe_id: int, user: CurrentUser, session: Session) -> Response:
    await _visible(session, user.id, recipe_id)
    row = await session.get(RecipeNote, (user.id, recipe_id))
    if row is not None:
        await session.delete(row)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def note_out(row: RecipeNote | None) -> RecipeNoteOut | None:
    if row is None:
        return None
    return RecipeNoteOut(note=row.note, rating=row.rating, updated_at=row.updated_at)


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
    return await recipe_detail(session, recipe, viewer)


async def recipe_detail(session: AsyncSession, recipe: Recipe, viewer: int | None) -> RecipeDetail:
    """A loaded recipe (with its ingredients) as the API shows it; `viewer` adds their pantry,
    verdict and what a serving costs them, None (a share link) shows the recipe alone."""
    food_ids = {i.food_id for i in recipe.ingredients if i.food_id is not None}
    foods = {f.id: f for f in await session.scalars(select(Food).where(Food.id.in_(food_ids)))}
    stocked = await _stocked(session, viewer, food_ids) if viewer else set[int]()
    info = {fid: planning.food_info(f) for fid, f in foods.items()}
    facts = planning.recipe_facts(recipe, foods, info)
    pricer = await planning.pricer_for(session, viewer) if viewer else None
    cost = (
        planning.serving_cost(
            (
                (
                    fid,
                    planning.portion_grams(line.grams, recipe.servings, info[fid].staple) * 2,
                    info[fid].price.pence_per_kg,
                    foods[fid].category,
                )
                for line in recipe.ingredients
                if (fid := line.food_id) is not None and fid in info
            ),
            pricer,
        )
        if pricer is not None and recipe.servings
        else None
    )
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
        minutes=recipe.minutes,
        instructions=recipe.instructions,
        generated=recipe.owner_user_id is not None,
        source=recipe.source,
        source_url=recipe.source_url,
        servings=recipe.servings,
        servings_estimated=recipe.servings_estimated,
        per_serving=per_serving,
        cost_per_serving=cost,
        currency=pricer.currency if pricer is not None else None,
        grade=recipe_grade(recipe, foods),
        feedback=verdict_of(await session.get(Preferences, viewer), recipe.id) if viewer else None,
        note=note_out(await session.get(RecipeNote, (viewer, recipe.id))) if viewer else None,
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
                in_pantry=i.food_id in stocked,
            )
            for i in sorted(recipe.ingredients, key=lambda i: i.position)
        ],
    )


async def _stocked(session: Session, user_id: int, food_ids: set[int]) -> set[int]:
    """Which of `food_ids` the user has in their pantry (a product counts as its generic)."""
    key = func.coalesce(Food.generic_food_id, PantryItem.food_id)
    rows = await session.scalars(
        select(key)
        .select_from(PantryItem)
        .join(Food, Food.id == PantryItem.food_id)
        .where(PantryItem.user_id == user_id, PantryItem.grams > 0, key.in_(food_ids))
    )
    return set(rows)


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


# --- import from a web page or typed text ------------------------------------------------------

_BREAKFAST = ("breakfast", "brunch")
_SNACK = ("snack", "dessert", "baking", "drink", "smoothie")


def guess_slot(category: str | None, name: str) -> Slot:
    words = f"{category or ''} {name}".lower()
    if any(w in words for w in _BREAKFAST):
        return Slot.BREAKFAST
    if any(w in words for w in _SNACK):
        return Slot.SNACK
    return Slot.DINNER


def draft_of(found: ImportedRecipe, url: str) -> ImportDraft:
    """The page's recipe as an editable draft, trimmed to what a saved recipe allows."""
    ingredients: list[ImportIngredient] = []
    for line in found.ingredients[:25]:
        quantity, name = split_line(line)
        ingredients.append(
            ImportIngredient(line=line[:300], name=name[:120], quantity=quantity[:40])
        )
    return ImportDraft.model_construct(
        name=found.name[:120],
        slot=guess_slot(found.category, found.name),
        servings=min(max(found.servings or 4, 1), 8),
        cuisine=(found.cuisine or None) and found.cuisine[:40],
        ingredients=ingredients,
        instructions=found.instructions[:4000],
        image_url=found.image_url if found.image_url and len(found.image_url) <= 2000 else None,
        source_url=url,
    )


@router.post(
    "/import/read",
    operation_id="readRecipePage",
    dependencies=[Depends(per_user("import_read"))],
    responses={422: {"description": "no recipe found, or the address can't be used"}},
)
async def read_recipe_page(body: ImportReadIn, user: CurrentUser) -> ImportDraft:
    """Read the recipe a web page publishes for search engines (schema.org JSON-LD) into a
    draft to check and save. Nothing is saved yet."""
    try:
        found = await recipe_import.fetch_recipe(body.url)
    except recipe_import.ImportError_ as e:
        logger.info("recipe import for user %s refused: %s", user.id, e)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    return draft_of(found, body.url.strip())


@router.post(
    "/import",
    operation_id="importRecipe",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(per_user("import_save"))],
)
async def import_recipe(
    body: ImportDraft,
    user: CurrentUser,
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    cache: Annotated[planning.CatalogCache, Depends(get_catalog_cache)],
    planner: Annotated[planning.Planner, Depends(get_replan_planner)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ImportResultOut:
    """Check and save a draft as the user's own recipe (changes.create: ingredients matched to
    foods, amounts weighed, nutrition from food data, the planner's allergy and diet checks).
    Problems come back to fix instead of a recipe."""
    now = clock()
    scope = replans.app_scope(
        user.id,
        today=local_today(user.timezone, now),
        local_time=None,
        now=now,
        sessionmaker=sessionmaker,
        catalog=cache,
        planner=planner,
        settings=settings,
    )
    created = await create_recipe(
        scope,
        _draft(body),
        source="imported",
        source_url=_web_address(body.source_url),
        image_url=_web_address(body.image_url),
    )
    return ImportResultOut(recipe_id=created.recipe_id, problems=created.problems)


def _draft(body: ImportDraft) -> CreateRecipeInput:
    return CreateRecipeInput(
        name=body.name,
        slot=body.slot,
        servings=body.servings,
        cuisine=body.cuisine,
        ingredients=[
            DraftIngredient(name=i.name, quantity=i.quantity or "1") for i in body.ingredients
        ],
        instructions=body.instructions,
    )


@router.put(
    "/{recipe_id}",
    operation_id="editRecipe",
    responses=_NOT_FOUND,
    dependencies=[Depends(per_user("import_save"))],
)
async def edit_recipe(
    recipe_id: int,
    body: ImportDraft,
    user: CurrentUser,
    session: Session,
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    cache: Annotated[planning.CatalogCache, Depends(get_catalog_cache)],
    planner: Annotated[planning.Planner, Depends(get_replan_planner)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ImportResultOut:
    """Change a recipe, checked exactly like a new one. The user's own recipe changes in place
    (its id stays, so favourites, plans and links keep pointing at it; meals already planned
    keep the numbers they were planned with). A catalogue recipe is saved as the user's own
    copy ("custom", with the original's photo), the original untouched for everyone else."""
    recipe = await session.scalar(
        select(Recipe).where(
            Recipe.id == recipe_id,
            or_(Recipe.owner_user_id.is_(None), Recipe.owner_user_id == user.id),
        )
    )
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")
    mine = recipe.owner_user_id == user.id
    photo, link = recipe.image_url, recipe.source_url
    await session.commit()  # create_recipe uses its own sessions
    now = clock()
    scope = replans.app_scope(
        user.id,
        today=local_today(user.timezone, now),
        local_time=None,
        now=now,
        sessionmaker=sessionmaker,
        catalog=cache,
        planner=planner,
        settings=settings,
    )
    created = await create_recipe(
        scope,
        _draft(body),
        source="custom",
        source_url=link,
        image_url=photo,
        replacing=recipe_id if mine else None,
    )
    return ImportResultOut(
        recipe_id=created.recipe_id,
        problems=created.problems,
        copied=not mine and created.recipe_id is not None,
    )


def _web_address(url: str | None) -> str | None:
    return url if url and url.startswith(("https://", "http://")) else None
