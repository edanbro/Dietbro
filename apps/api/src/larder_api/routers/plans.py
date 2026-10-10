"""Weekly plans: generate (prefilter + plan + validate + save), read, and the shopping list.

Every query is filtered by the signed-in user; other users' plans are 404s.
"""

import logging
import math
import time
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_api.auth import CurrentUser
from larder_api.db import Session, get_sessionmaker
from larder_api.schemas import (
    DayOut,
    MacrosOut,
    MealOut,
    PlanOut,
    PlanRequest,
    Problems,
    RecipeCard,
    ShoppingItemOut,
    ShoppingItemPatch,
    ShoppingListOut,
)
from larder_api.settings import Settings, get_settings
from larder_core.meals import SLOT_ORDER, Slot
from larder_core.quantities import Portion
from larder_db.models import Food, FoodPortion, MealPlan, PlanMeal, ShoppingItem, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plans", tags=["plans"])

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": "no such plan (or not yours)"}
}
_CREATE_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: {
        "model": Problems,
        "description": "bad start date, or no plan fits (reasons)",
    },
    status.HTTP_409_CONFLICT: {
        "model": Problems,
        "description": "setup incomplete (goals, allergies, preferences) or goals need review",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": Problems,
        "description": "the planner found no plan in time",
    },
}

# Units shown as "≈ 2 medium" on the shopping list, in order of preference.
_FRIENDLY_UNITS = ("medium", "large", "whole", "small", "clove", "slice")


def get_catalog_cache(request: Request) -> planning.CatalogCache:
    cache: planning.CatalogCache | None = getattr(request.app.state, "catalog", None)
    if cache is None:
        cache = request.app.state.catalog = planning.CatalogCache()
    return cache


_limiter: anyio.CapacityLimiter | None = None


def plan_limiter(settings: Settings) -> anyio.CapacityLimiter:
    """Process-wide cap on concurrent solves (each uses several CPU threads)."""
    global _limiter
    if _limiter is None:
        _limiter = anyio.CapacityLimiter(settings.plan_concurrency)
    return _limiter


def get_planner(settings: Annotated[Settings, Depends(get_settings)]) -> planning.Planner:
    return partial(
        planning.run_planner,
        mode=settings.planner,
        time_limit_ms=settings.plan_time_limit_ms,
        workers=settings.plan_workers,
    )


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _card(meal: PlanMeal) -> RecipeCard:
    r = meal.recipe
    return RecipeCard(
        id=r.id, name=r.name, category=r.category, cuisine=r.cuisine, image_url=r.image_url
    )


def plan_out(row: MealPlan) -> PlanOut:
    """Built only from stored rows and the stats snapshot, never from live goals or prices."""
    stats = planning.PlanStats.model_validate(row.stats)
    by_day: dict[int, list[PlanMeal]] = {}
    for meal in row.meals:
        by_day.setdefault(meal.day, []).append(meal)
    days: list[DayOut] = []
    for d, day_date in enumerate(planning.plan_dates(row.start_date, row.days)):
        meals = sorted(by_day.get(d, []), key=lambda m: SLOT_ORDER.index(Slot(m.slot)))
        days.append(
            DayOut(
                day=d,
                date=day_date,
                meals=[
                    MealOut(
                        slot=Slot(m.slot),
                        recipe=_card(m),
                        portions=m.portions,
                        servings=m.portions / 2,
                        nutrition=MacrosOut(
                            kcal=m.kcal, protein_g=m.protein_g, fat_g=m.fat_g, carbs_g=m.carbs_g
                        ),
                        locked=m.locked,
                        status=m.status,  # pyright: ignore[reportArgumentType]
                    )
                    for m in meals
                ],
                totals=stats.day_totals[d],
                logged=[],  # M4: meal_logs for day_date
            )
        )
    week = MacrosOut(
        kcal=sum(t.kcal for t in stats.day_totals),
        protein_g=sum(t.protein_g for t in stats.day_totals),
        fat_g=sum(t.fat_g for t in stats.day_totals),
        carbs_g=sum(t.carbs_g for t in stats.day_totals),
    )
    return PlanOut(
        id=row.id,
        version=row.version,
        parent_id=row.parent_id,
        start=row.start_date,
        days=days,
        planner=row.planner,
        status=row.status,
        created_at=row.created_at,
        solve_ms=row.solve_ms,
        currency=row.currency,  # pyright: ignore[reportArgumentType]
        targets=stats.targets,
        week_totals=week,
        cost_minor=stats.cost_minor,
        budget_minor=stats.budget_minor,
        pantry_used_g=stats.pantry_used_g,
        waste_g=stats.waste_g,
        shopping_items=sum(1 for s in row.shopping if not s.staple),
        excluded_allergens=stats.excluded_allergens,
        diet=stats.diet,
        violations=stats.violations,
        notes=stats.notes,
    )


async def _load_plan(session: AsyncSession, user: User, plan_id: int) -> MealPlan:
    row = await session.scalar(
        select(MealPlan)
        .where(MealPlan.id == plan_id, MealPlan.user_id == user.id)
        .options(
            selectinload(MealPlan.meals).selectinload(PlanMeal.recipe),
            selectinload(MealPlan.shopping),
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "plan not found")
    return row


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    operation_id="createPlan",
    responses=_CREATE_ERRORS,
)
async def create_plan(
    body: PlanRequest,
    user: CurrentUser,
    session: Session,
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    cache: Annotated[planning.CatalogCache, Depends(get_catalog_cache)],
    planner: Annotated[planning.Planner, Depends(get_planner)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlanOut:
    started = time.perf_counter()
    today = _utc_today()
    start = body.start or today
    if not today - timedelta(days=1) <= start <= today + timedelta(days=7):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, ["Pick a start date between today and a week ahead."]
        )
    try:
        inputs = await planning.load_inputs(session, user)
    except planning.SetupIncomplete as e:
        raise HTTPException(status.HTTP_409_CONFLICT, e.missing) from e
    if problems := planning.goal_problems(inputs):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            [*problems, "Please review your goals in your profile before planning."],
        )
    catalog = await cache.get(sessionmaker)
    current = await planning.latest_plan(session, user.id)
    version = await planning.next_version(session, user.id, start)
    seed = planning.plan_seed(user.id, start, version)
    novelty = frozenset(m.recipe_id for m in current.meals) if current else frozenset[int]()
    problem = planning.make_problem(
        inputs, catalog, start, k=settings.plan_candidates, seed=seed, novelty=novelty
    )
    prepared = planning.Prepared(problem, version, seed, current.id if current else None, novelty)
    currency = inputs.goals.currency
    # Release the DB connection while the solver runs.
    await session.commit()

    result = await anyio.to_thread.run_sync(planner, problem, limiter=plan_limiter(settings))
    try:
        plan, violations = planning.check_outcome(problem, result)
    except planning.PlanningError as e:
        raise HTTPException(e.status_code, e.detail) from e
    stats = planning.plan_stats(
        problem, result, plan, violations, seed=seed, time_limit_ms=settings.plan_time_limit_ms
    )
    stats.total_ms = round((time.perf_counter() - started) * 1000)

    row = planning.save_plan(
        session, user.id, prepared, result, plan, stats, currency, catalog.unshoppable
    )
    try:
        await session.commit()
    except IntegrityError:
        # Two plans for the same start at once: take the next version and retry once.
        await session.rollback()
        prepared.version = await planning.next_version(session, user.id, start)
        row = planning.save_plan(
            session, user.id, prepared, result, plan, stats, currency, catalog.unshoppable
        )
        await session.commit()
    return plan_out(await _load_plan(session, user, row.id))


@router.get("/current", operation_id="getCurrentPlan")
async def current_plan(user: CurrentUser, session: Session) -> PlanOut | None:
    """The most recently created plan, or null if there is none."""
    latest = await planning.latest_plan(session, user.id)
    return plan_out(await _load_plan(session, user, latest.id)) if latest else None


@router.get("/{plan_id}", operation_id="getPlan", responses=_NOT_FOUND)
async def get_plan(plan_id: int, user: CurrentUser, session: Session) -> PlanOut:
    return plan_out(await _load_plan(session, user, plan_id))


def approx_units(grams: int, portions: list[Portion]) -> str | None:
    """'≈ 2 medium' for foods with a natural count unit; None when it wouldn't help."""
    each = {p.unit: p.grams for p in portions if p.amount == 1 and p.grams > 0}
    unit = next((u for u in _FRIENDLY_UNITS if u in each), None)
    if unit is None:
        return None
    n = math.ceil(2 * grams / each[unit]) / 2
    if not 0.5 <= n <= 24:
        return None
    whole = int(n)
    count = (str(whole) if whole else "") + ("½" if n != whole else "")
    return f"≈ {count} {unit}"


async def _shopping_out(session: AsyncSession, plan: MealPlan) -> ShoppingListOut:
    food_ids = [s.food_id for s in plan.shopping]
    foods = {f.id: f for f in await session.scalars(select(Food).where(Food.id.in_(food_ids)))}
    portions: dict[int, list[Portion]] = {}
    for p in await session.scalars(select(FoodPortion).where(FoodPortion.food_id.in_(food_ids))):
        portions.setdefault(p.food_id, []).append(Portion(p.amount, p.unit, p.qualifier, p.grams))
    stats = planning.PlanStats.model_validate(plan.stats)

    def item(s: ShoppingItem) -> ShoppingItemOut:
        food = foods[s.food_id]
        return ShoppingItemOut(
            food_id=s.food_id,
            name=food.description,
            category=food.category,
            grams=s.grams,
            cost_minor=s.cost_minor,
            checked=s.checked,
            staple=s.staple,
            approx_units=None if s.staple else approx_units(s.grams, portions.get(s.food_id, [])),
        )

    items = sorted(
        (item(s) for s in plan.shopping),
        key=lambda i: (i.staple, i.category or "", i.name.casefold(), i.food_id),
    )
    return ShoppingListOut(
        plan_id=plan.id,
        currency=plan.currency,  # pyright: ignore[reportArgumentType]
        total_minor=stats.cost_minor,
        budget_minor=stats.budget_minor,
        items=items,
    )


@router.get("/{plan_id}/shopping", operation_id="getShoppingList", responses=_NOT_FOUND)
async def shopping_list(plan_id: int, user: CurrentUser, session: Session) -> ShoppingListOut:
    return await _shopping_out(session, await _load_plan(session, user, plan_id))


@router.patch(
    "/{plan_id}/shopping/{food_id}", operation_id="patchShoppingItem", responses=_NOT_FOUND
)
async def patch_shopping_item(
    plan_id: int, food_id: int, body: ShoppingItemPatch, user: CurrentUser, session: Session
) -> ShoppingItemOut:
    plan = await _load_plan(session, user, plan_id)
    line = next((s for s in plan.shopping if s.food_id == food_id), None)
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not on this shopping list")
    line.checked = body.checked
    await session.commit()
    out = await _shopping_out(session, await _load_plan(session, user, plan_id))
    return next(i for i in out.items if i.food_id == food_id)
