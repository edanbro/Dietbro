"""Weekly plans: generate (prefilter + plan + validate + save), read, the shopping list, plan
changes from the plan screen (POST /plans/replan, larder_api.replans) and meals marked eaten
(larder_api.eaten).

A new plan is made around food already logged in its dates (active meal_logs, from the chat):
a logged meal stays empty, every log counts on its day (with the replan day bands) and shows
in the plan's `logged`, like a chat replan's version.

Every query is filtered by the signed-in user; other users' plans are 404s.
"""

import logging
import math
import time
from datetime import date, timedelta
from functools import partial
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from larder_api import eaten, planning, replans
from larder_api.auth import CurrentUser
from larder_api.chat import search
from larder_api.clock import Clock, get_clock
from larder_api.db import Session, get_sessionmaker
from larder_api.planning import plan_limiter
from larder_api.prep_ahead import ahead_for
from larder_api.ratelimit import per_user
from larder_api.routers.pantry import out as pantry_out
from larder_api.schemas import (
    AheadOut,
    ChatProblem,
    DayMealOut,
    DayOut,
    EatenIn,
    EatenOut,
    MacrosOut,
    OutcomeOut,
    PantryItemOut,
    PlanOut,
    PlanRequest,
    Problems,
    RecipeCard,
    RecipeListItem,
    ReplanRequest,
    ShoppingItemOut,
    ShoppingItemPatch,
    ShoppingListOut,
    StockIn,
    UsedInOut,
)
from larder_api.settings import Settings, get_settings
from larder_core.meals import SLOT_ORDER, Slot
from larder_core.quantities import Portion
from larder_core.regions import local_today
from larder_core.shelf_life import suggest_expiry
from larder_db.models import (
    Food,
    FoodPortion,
    MealLog,
    MealPlan,
    PantryItem,
    PlanMeal,
    PlanTemplate,
    Recipe,
    RecipeIngredient,
    ShoppingItem,
    User,
)
from larder_solver import Plan, PlanResult, Problem, Violation

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

_EATEN_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: {
        "model": Problems,
        "description": "`today` is implausible, or `date` is after it",
    },
    status.HTTP_404_NOT_FOUND: {
        "description": "no such plan (or not yours), date not in it, or no meal there"
    },
    status.HTTP_409_CONFLICT: {
        "model": Problems,
        "description": "the plan isn't the latest version (reload it)",
    },
}
REPLAN_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: {"model": ChatProblem, "description": "bad_today"},
    status.HTTP_409_CONFLICT: {
        "model": ChatProblem,
        "description": "busy: a plan change (chat or plan screen) is running; duplicate: this "
        "client_id was already applied (reload the plan)",
    },
}

# Units shown as "≈ 2 medium" on the shopping list, in order of preference.
_FRIENDLY_UNITS = ("medium", "large", "whole", "small", "clove", "slice")


def get_catalog_cache(request: Request) -> planning.CatalogCache:
    cache: planning.CatalogCache | None = getattr(request.app.state, "catalog", None)
    if cache is None:
        cache = request.app.state.catalog = planning.CatalogCache()
    return cache


def get_planner(settings: Annotated[Settings, Depends(get_settings)]) -> planning.Planner:
    return partial(
        planning.run_planner,
        mode=settings.planner,
        time_limit_ms=settings.plan_time_limit_ms,
        workers=settings.plan_workers,
    )


def get_replan_planner(settings: Annotated[Settings, Depends(get_settings)]) -> planning.Planner:
    """The planner chat replans use: the same one with a shorter budget per run (at most three
    runs per request, docs/adr/0014-chat-replans.md)."""
    return partial(
        planning.run_planner,
        mode=settings.planner,
        time_limit_ms=settings.replan_time_limit_ms,
        workers=settings.plan_workers,
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
        out = [planning.meal_out(m) for m in meals]
        days.append(
            DayOut(
                day=d,
                date=day_date,
                meals=out,
                totals=planning.add_extras(stats.day_totals[d], (m.nutrition for m in out)),
                logged=stats.logged_on(d),
            )
        )
    week = planning.add_extras(
        MacrosOut(
            kcal=sum(t.kcal for t in stats.day_totals),
            protein_g=sum(t.protein_g for t in stats.day_totals),
            fat_g=sum(t.fat_g for t in stats.day_totals),
            carbs_g=sum(t.carbs_g for t in stats.day_totals),
        ),
        (day.totals for day in days),
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
        household=stats.household,
        own_meals=stats.own_meals,
        skipped_meals=stats.skipped_meals,
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


_FRESH_NOTE = (
    "Those meals don't all fit your goals as they are now, so this week was planned fresh."
)
_QUICK_NOTE = "Not every busy night could have a quick dinner that fits your goals this week."


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    operation_id="createPlan",
    responses=_CREATE_ERRORS,
    dependencies=[Depends(per_user("plan"))],
)
async def create_plan(
    body: PlanRequest,
    user: CurrentUser,
    session: Session,
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    cache: Annotated[planning.CatalogCache, Depends(get_catalog_cache)],
    planner: Annotated[planning.Planner, Depends(get_planner)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> PlanOut:
    started = time.perf_counter()
    today = local_today(user.timezone, clock())
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
    private = await planning.load_private_recipes(session, user.id)
    current = await planning.plan_for(session, user.id, today)
    version = await planning.next_version(session, user.id, start)
    seed = planning.plan_seed(user.id, start, version)
    # Planning a week again (an earlier week or a saved template): its meals, where they
    # still suit the user (planning.repeat_choices). Novelty would only fight that.
    cells = await _repeat_cells(session, user.id, body)
    novelty = (
        frozenset(m.recipe_id for m in current.meals)
        if current and cells is None
        else frozenset[int]()
    )
    fresh = planning.make_problem(
        inputs,
        catalog,
        start,
        k=settings.plan_candidates,
        seed=seed,
        novelty=novelty,
        private=private,
    )
    pool = catalog.merged(private)
    repeat: dict[planning.Cell, tuple[int, ...]] = {}
    repeat_notes: list[str] = []
    if cells:
        repeat, dropped = planning.repeat_choices(fresh, inputs, pool, cells)
        if dropped:
            repeat_notes.append(await planning.left_out_note(session, dropped))
    # Busy nights: quick dinners on the user's chosen weekdays (a repeated meal wins its cell).
    quick = planning.quick_choices(fresh, inputs, pool)
    # Food already logged in these dates (chat) keeps its meal empty and counts on its day.
    logs = await planning.active_logs(session, user.id, start, fresh.days)
    currency = inputs.goals.currency
    # Release the DB connection while the solver runs.
    await session.commit()

    async def solve(p: Problem) -> tuple[PlanResult, Plan, list[Violation]]:
        result = await anyio.to_thread.run_sync(planner, p, None, limiter=plan_limiter(settings))
        plan, violations = planning.check_outcome(p, result)
        return result, plan, violations

    # What the user asked for first; when it can't fit their goals as they are now, without
    # the quick dinners, then without the repeated meals, then fresh.
    attempts: list[tuple[dict[planning.Cell, tuple[int, ...]], list[str]]] = []
    for keep_repeat in (True, False) if repeat else (False,):
        for keep_quick in (True, False) if quick else (False,):
            attempts.append(
                (
                    {**(quick if keep_quick else {}), **(repeat if keep_repeat else {})},
                    [
                        *(repeat_notes if keep_repeat else [_FRESH_NOTE] if repeat else []),
                        *([] if keep_quick or not quick else [_QUICK_NOTE]),
                    ],
                )
            )
    *earlier, (last_choices, last_notes) = attempts
    for choices, attempt_notes in earlier:
        problem = _with_choices(fresh, inputs, pool, choices, logs)
        try:
            result, plan, violations = await solve(problem)
            notes = attempt_notes
            break
        except planning.PlanningError:
            continue
    else:
        problem = _with_choices(fresh, inputs, pool, last_choices, logs)
        try:
            result, plan, violations = await solve(problem)
        except planning.PlanningError as e:
            raise HTTPException(e.status_code, e.detail) from e
        notes = last_notes
    prepared = planning.Prepared(problem, version, seed, None, novelty)
    stats = planning.plan_stats(
        problem,
        result,
        plan,
        violations,
        seed=seed,
        time_limit_ms=settings.plan_time_limit_ms,
        household=planning.household_of(inputs, problem.days),
        own=planning.own_meals(inputs),
        skipped=planning.skipped_meals(inputs),
    )
    stats.notes = [*notes, *stats.notes]
    stats.total_ms = round((time.perf_counter() - started) * 1000)
    stats.logged = planning.logged_by_day(logs, start, problem.days)

    # One save at a time per user (chat replans take the same lock): the version and the
    # parent are read under it.
    await planning.lock_user_plans(session, user.id)
    latest = await planning.plan_for(session, user.id, start)
    prepared.parent_id = latest.id if latest else None
    prepared.version = await planning.next_version(session, user.id, start)
    unshoppable = catalog.unshoppable | private.unshoppable
    row = planning.save_plan(session, user.id, prepared, result, plan, stats, currency, unshoppable)
    await session.commit()
    return await with_pantry(session, user.id, plan_out(await _load_plan(session, user, row.id)))


def _with_choices(
    fresh: Problem,
    inputs: planning.UserInputs,
    pool: planning.PlanningCatalog,
    choices: dict[planning.Cell, tuple[int, ...]],
    logs: list[MealLog],
) -> Problem:
    """The fresh problem with these per-cell choices and the food already logged."""
    constrained = (
        planning.constrain(fresh, inputs, pool, choices=choices, extra={}) if choices else fresh
    )
    return planning.with_logs(constrained, inputs, pool, logs)


async def _repeat_cells(
    session: AsyncSession, user_id: int, body: PlanRequest
) -> list[tuple[int, Slot, int]] | None:
    """The meals to plan again, or None for a fresh plan."""
    if body.template_id is not None:
        template = await session.scalar(
            select(PlanTemplate).where(
                PlanTemplate.id == body.template_id, PlanTemplate.user_id == user_id
            )
        )
        if template is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, ["That template doesn't exist."])
        return planning.template_cells(template)
    if body.repeat_from is not None:
        cells = await planning.week_cells(session, user_id, body.repeat_from)
        if not cells:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, ["There's no plan for that week to repeat."]
            )
        return cells
    return None


@router.post(
    "/replan",
    operation_id="replanPlan",
    responses=REPLAN_ERRORS,
    dependencies=[Depends(per_user("plan"))],
)
async def replan_plan(
    body: ReplanRequest,
    response: Response,
    user: CurrentUser,
    session: Session,
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    cache: Annotated[planning.CatalogCache, Depends(get_catalog_cache)],
    planner: Annotated[planning.Planner, Depends(get_replan_planner)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> OutcomeOut:
    """Apply plan changes (skip, swap, craving, food eaten off-plan) without the chat: the
    chat's executor, so the same rules, results and new plan version. Server-Timing has the
    replan's wall time."""
    timed = await replans.run(
        session,
        user.id,
        body,
        sessionmaker=sessionmaker,
        catalog=cache,
        planner=planner,
        settings=settings,
        now=clock(),
    )
    response.headers["Server-Timing"] = timed.server_timing
    return OutcomeOut.model_validate(timed.outcome.model_dump())


@router.get("/current", operation_id="getCurrentPlan")
async def current_plan(
    user: CurrentUser,
    session: Session,
    clock: Annotated[Clock, Depends(get_clock)],
    on: Annotated[date | None, Query(alias="date", description="default: today")] = None,
) -> PlanOut | None:
    """The plan in force on `date` (the newest version covering it, else the newest plan), or
    null if there is none. Next week's plan doesn't replace this week's for this week's dates."""
    day = on or local_today(user.timezone, clock())
    plan_id = await planning.plan_id_for(session, user.id, day)
    if plan_id is None:
        return None
    return await with_pantry(session, user.id, plan_out(await _load_plan(session, user, plan_id)))


@router.get("/upcoming", operation_id="getUpcomingPlan")
async def upcoming_plan(
    user: CurrentUser, session: Session, clock: Annotated[Clock, Depends(get_clock)]
) -> PlanOut | None:
    """The plan for the days after the current one ends ("next week"), or null."""
    today = local_today(user.timezone, clock())
    current = await planning.plan_for(session, user.id, today)
    if current is None:
        return None
    after = current.start_date + timedelta(days=current.days)
    plan_id = await planning.plan_id_for(session, user.id, after)
    if plan_id is None or plan_id == current.id:
        return None
    row = await _load_plan(session, user, plan_id)
    covers = row.start_date <= after < row.start_date + timedelta(days=row.days)
    if not covers or row.start_date <= today:
        return None
    return await with_pantry(session, user.id, plan_out(row))


@router.get("/meals", operation_id="getMealsOn")
async def meals_on(on: date, user: CurrentUser, session: Session) -> list[DayMealOut]:
    """The meals planned on a date (the newest plan covering it), to copy to another day."""
    cells = await planning.week_cells(session, user.id, on, days=1)
    recipes = {
        r.id: r
        for r in await session.scalars(
            select(Recipe).where(Recipe.id.in_({rid for _, _, rid in cells}))
        )
    }
    return [
        DayMealOut(slot=slot, recipe=RecipeCard.model_validate(recipes[rid], from_attributes=True))
        for _, slot, rid in sorted(cells, key=lambda c: SLOT_ORDER.index(c[1]))
        if rid in recipes
    ]


@router.get("/ahead", operation_id="getPrepAhead")
async def prep_ahead(
    user: CurrentUser,
    session: Session,
    clock: Annotated[Clock, Depends(get_clock)],
    on: date | None = None,
) -> AheadOut:
    """What the meals planned on `on` (default: tomorrow, the user's date) need doing the
    evening before: food to take out of the freezer, and steps to start (larder_api.prep_ahead)."""
    day = on or local_today(user.timezone, clock()) + timedelta(days=1)
    return AheadOut(date=day, items=await ahead_for(session, user.id, day))


@router.get(
    "/{plan_id}/alternatives",
    operation_id="getMealAlternatives",
    responses=_NOT_FOUND | {409: {"description": "setup incomplete"}},
)
async def meal_alternatives(
    plan_id: int,
    on: Annotated[date, Query(alias="date")],
    slot: Slot,
    user: CurrentUser,
    session: Session,
    cache: Annotated[planning.CatalogCache, Depends(get_catalog_cache)],
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    limit: Annotated[int, Query(ge=1, le=6)] = 3,
    q: Annotated[str, Query(max_length=80)] = "",
    quick: bool = False,
    pantry: bool = False,
    favourites: bool = False,
    cheaper: bool = False,
) -> list[RecipeListItem]:
    """A few safe recipes to swap a planned meal for (then POST /plans/replan with a swap and
    its recipe_id): ranked like recipe search, not already planned that day, close to the
    meal's energy first. `q` searches like recipe search ("curry", "something quick");
    `quick` keeps those taking at most 30 minutes; `pantry`, those using the pantry;
    `favourites`, the user's favourites; `cheaper` puts the lowest cost a serving first."""
    plan = await _load_plan(session, user, plan_id)
    day = (on - plan.start_date).days
    if not 0 <= day < plan.days:
        raise HTTPException(status.HTTP_404_NOT_FOUND, ["That day isn't in this plan."])
    viewer = await search.viewer_of(session, user.id)
    if viewer is None:
        raise HTTPException(status.HTTP_409_CONFLICT, ["Finish setting up first."])
    pool = (await cache.get(sessionmaker)).merged(
        await planning.load_private_recipes(session, user.id)
    )
    that_day = {m.recipe_id for m in plan.meals if m.day == day}
    meal = next((m for m in plan.meals if m.day == day and m.slot == slot), None)
    target = round(meal.kcal * 2 / max(meal.portions, 1)) if meal else None
    words, minutes = search.time_limit(search.query_words(q))
    if quick:
        minutes = search.QUICK_MINUTES
    if q.strip() and not (words or minutes):
        return []
    pricer = await planning.pricer_for(session, user.id) if cheaper else None
    hits = [
        h
        for h in search.rank_recipes(
            pool,
            viewer,
            words,
            slot,
            favourites_only=favourites,
            max_minutes=minutes,
            from_pantry=pantry,
            pricer=pricer,
        )
        if h.id not in that_day
    ]
    if cheaper:  # stable: ties keep the ranking above
        hits.sort(key=lambda h: (h.cost_per_serving is None, h.cost_per_serving or 0))

    def close(kcal: int) -> bool:
        return target is None or abs(kcal - target) <= 0.35 * target

    # Searched for (or cheapest asked for): in that order. Otherwise those close to the meal's
    # energy first.
    picked = [] if words or cheaper else [h for h in hits if close(h.kcal_per_serving)][:limit]
    picked += [h for h in hits if h not in picked][: limit - len(picked)]
    return [
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
            cost_per_serving=h.cost_per_serving,
        )
        for h in picked
    ]


_UNDO_ERRORS: dict[int | str, dict[str, Any]] = _NOT_FOUND | {
    status.HTTP_409_CONFLICT: {"model": Problems, "description": "nothing to undo, or too late"}
}


@router.post("/{plan_id}/undo", operation_id="undoPlanChange", responses=_UNDO_ERRORS)
async def undo_plan_change(plan_id: int, user: CurrentUser, session: Session) -> PlanOut:
    """Bring back the version before the last change (as a new version: history is kept).
    Only the newest version of a week can be undone, only when it came from a change to that
    week, and not once food has been logged or meals marked eaten since that change."""
    await planning.lock_user_plans(session, user.id)
    plan = await _load_plan(session, user, plan_id)
    newer = await session.scalar(
        select(MealPlan.id).where(
            MealPlan.user_id == user.id,
            MealPlan.start_date == plan.start_date,
            MealPlan.version > plan.version,
        )
    )
    if newer is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, ["Your plan has changed - reload it and try again."]
        )
    parent = await _load_plan(session, user, plan.parent_id) if plan.parent_id else None
    if parent is None or parent.start_date != plan.start_date:
        raise HTTPException(status.HTTP_409_CONFLICT, ["There's no change to undo."])
    logged = await session.scalar(
        select(MealLog.id)
        .where(
            MealLog.user_id == user.id,
            or_(MealLog.created_at >= plan.created_at, MealLog.voided_at >= plan.created_at),
        )
        .limit(1)
    )
    if logged is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            [
                "Food was logged or a meal marked eaten since that change, so it can't be "
                "undone. Ask the chat to change it back instead."
            ],
        )
    restored = MealPlan(
        user_id=user.id,
        start_date=parent.start_date,
        days=parent.days,
        version=await planning.next_version(session, user.id, parent.start_date),
        parent_id=plan.id,
        planner=parent.planner,
        status=parent.status,
        objective=parent.objective,
        solve_ms=parent.solve_ms,
        currency=parent.currency,
        stats=parent.stats,
    )
    restored.meals.extend(planning.copy_meal(m) for m in parent.meals)
    ticked = {s.food_id: s for s in plan.shopping}
    for item in parent.shopping:
        now = ticked.get(item.food_id)
        keep = now is not None and item.grams <= now.grams
        restored.shopping.append(
            ShoppingItem(
                food_id=item.food_id,
                grams=item.grams,
                cost_minor=item.cost_minor,
                staple=item.staple,
                checked=keep and now is not None and now.checked,
                stocked_at=now.stocked_at if keep and now is not None else None,
            )
        )
    session.add(restored)
    await session.commit()
    return plan_out(await _load_plan(session, user, restored.id))


@router.get("/{plan_id}", operation_id="getPlan", responses=_NOT_FOUND)
async def get_plan(plan_id: int, user: CurrentUser, session: Session) -> PlanOut:
    return await with_pantry(session, user.id, plan_out(await _load_plan(session, user, plan_id)))


async def with_pantry(session: AsyncSession, user_id: int, plan: PlanOut) -> PlanOut:
    """Each meal's `uses_pantry`: what's in the pantry now that its recipe uses (a product
    counts as its generic). Read live, unlike the rest of the plan, which is a snapshot."""
    recipe_ids = {m.recipe.id for d in plan.days for m in d.meals}
    if not recipe_ids:
        return plan
    stock: dict[int, str] = {}
    for item in await session.scalars(
        select(PantryItem)
        .where(PantryItem.user_id == user_id, PantryItem.grams > 0)
        .options(selectinload(PantryItem.food))
    ):
        name = item.food.description.split(",", 1)[0].strip()
        stock.setdefault(item.food_id, name)
        if item.food.generic_food_id is not None:
            stock.setdefault(item.food.generic_food_id, name)
    if not stock:
        return plan
    uses: dict[int, list[str]] = {}
    for recipe_id, food_id in await session.execute(
        select(RecipeIngredient.recipe_id, RecipeIngredient.food_id)
        .where(RecipeIngredient.recipe_id.in_(recipe_ids), RecipeIngredient.food_id.in_(stock))
        .order_by(RecipeIngredient.recipe_id, RecipeIngredient.position)
    ):
        names = uses.setdefault(recipe_id, [])
        if food_id is not None and stock[food_id] not in names:
            names.append(stock[food_id])
    for day in plan.days:
        for meal in day.meals:
            meal.uses_pantry = uses.get(meal.recipe.id, [])
    return plan


@router.post("/{plan_id}/meals/eaten", operation_id="markMealEaten", responses=_EATEN_ERRORS)
async def mark_meal_eaten(
    plan_id: int,
    body: EatenIn,
    user: CurrentUser,
    session: Session,
    clock: Annotated[Clock, Depends(get_clock)],
) -> EatenOut:
    """Mark a meal of the current plan eaten: logged as eaten (counted by later replans, its
    slot kept) and its ingredients taken from the pantry. Repeating it changes nothing."""
    now = clock()
    eaten.check_dates(body.date, body.today, now)
    return await eaten.mark(session, user.id, plan_id, body.date, body.slot, now)


@router.delete("/{plan_id}/meals/eaten", operation_id="unmarkMealEaten", responses=_EATEN_ERRORS)
async def unmark_meal_eaten(
    plan_id: int,
    on: Annotated[date, Query(alias="date")],
    slot: Annotated[Slot, Query()],
    user: CurrentUser,
    session: Session,
    clock: Annotated[Clock, Depends(get_clock)],
) -> EatenOut:
    """Undo a meal marked eaten: the log is voided and the pantry gets back exactly what it
    gave (items deleted since are not recreated). Undoing twice changes nothing."""
    return await eaten.unmark(session, user.id, plan_id, on, slot, clock())


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


async def used_in(session: AsyncSession, plan: MealPlan) -> dict[int, list[UsedInOut]]:
    """Per food: the plan's recipes that use it, in the order they're first eaten."""
    rows = await session.execute(
        select(PlanMeal.day, PlanMeal.recipe_id, Recipe.name)
        .join(Recipe, Recipe.id == PlanMeal.recipe_id)
        .where(PlanMeal.plan_id == plan.id)
        .order_by(PlanMeal.day, PlanMeal.id)
    )
    recipes: dict[int, UsedInOut] = {}
    for day, recipe_id, name in rows:
        on = plan.start_date + timedelta(days=day)
        seen = recipes.setdefault(recipe_id, UsedInOut(recipe_id=recipe_id, name=name, dates=[]))
        if on not in seen.dates:
            seen.dates.append(on)
    lines = await session.execute(
        select(RecipeIngredient.food_id, RecipeIngredient.recipe_id).where(
            RecipeIngredient.recipe_id.in_(recipes), RecipeIngredient.food_id.is_not(None)
        )
    )
    out: dict[int, list[UsedInOut]] = {}
    for food_id, recipe_id in lines:
        if food_id is None:
            continue
        uses = out.setdefault(food_id, [])
        if recipes[recipe_id] not in uses:
            uses.append(recipes[recipe_id])
    order = list(recipes)
    return {f: sorted(uses, key=lambda u: order.index(u.recipe_id)) for f, uses in out.items()}


async def shopping_out(session: AsyncSession, plan: MealPlan) -> ShoppingListOut:
    """A plan's shopping list (`plan.shopping` loaded) as the API shows it."""
    food_ids = [s.food_id for s in plan.shopping]
    uses = await used_in(session, plan)
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
            stocked=s.stocked_at is not None,
            staple=s.staple,
            approx_units=None if s.staple else approx_units(s.grams, portions.get(s.food_id, [])),
            used_in=uses.get(s.food_id, []),
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
        household=stats.household,
        items=items,
    )


@router.get("/{plan_id}/shopping", operation_id="getShoppingList", responses=_NOT_FOUND)
async def shopping_list(plan_id: int, user: CurrentUser, session: Session) -> ShoppingListOut:
    return await shopping_out(session, await _load_plan(session, user, plan_id))


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
    out = await shopping_out(session, await _load_plan(session, user, plan_id))
    return next(i for i in out.items if i.food_id == food_id)


@router.post(
    "/{plan_id}/shopping/stock",
    status_code=status.HTTP_201_CREATED,
    operation_id="stockShoppingItems",
    responses=_NOT_FOUND,
)
async def stock_shopping_items(
    plan_id: int,
    body: StockIn,
    user: CurrentUser,
    session: Session,
    clock: Annotated[Clock, Depends(get_clock)],
) -> list[PantryItemOut]:
    """Move bought lines into the pantry (default: every ticked line not moved yet), in grams,
    with a suggested use-by date. Each line moves once; staples are never moved."""
    plan = await _load_plan(session, user, plan_id)
    wanted = set(body.food_ids) if body.food_ids is not None else None
    lines = [
        s
        for s in plan.shopping
        if not s.staple
        and s.stocked_at is None
        and s.grams > 0
        and (s.food_id in wanted if wanted is not None else s.checked)
    ]
    now = clock()
    today = local_today(user.timezone, now)
    foods = {
        f.id: f
        for f in await session.scalars(select(Food).where(Food.id.in_([s.food_id for s in lines])))
    }
    added: list[PantryItem] = []
    for line in lines:
        food = foods[line.food_id]
        item = PantryItem(
            user_id=user.id,
            food_id=food.id,
            grams=float(line.grams),
            quantity=float(line.grams),
            unit="g",
            approx=False,
            expires_on=suggest_expiry(today, food.description, food.category),
            source="shopping",
        )
        session.add(item)
        added.append(item)
        line.checked = True
        line.stocked_at = now
    await session.commit()
    for item in added:
        await session.refresh(item, ["food", "created_at"])
    return [pantry_out(i) for i in added]
