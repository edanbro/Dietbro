"""The food diary (what was eaten, day by day, against the goals) and weigh-ins.

Nothing new is stored for the diary: it reads the meal logs every replan already rebuilds
from (meals marked eaten, food logged off-plan, skips). Weigh-ins are one per day; the newest
is copied to the body profile so the energy targets follow the user's weight.
"""

import uuid
from datetime import date, timedelta
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api import planning, replans
from larder_api.auth import CurrentUser
from larder_api.changes import offplan
from larder_api.changes.foods import short_name
from larder_api.clock import Clock, get_clock
from larder_api.db import Session, get_sessionmaker
from larder_api.insights import monday, weekly_recap, weekly_spending
from larder_api.price_watch import load_lines, watch
from larder_api.ratelimit import per_user
from larder_api.routers.foods import summary
from larder_api.routers.plans import REPLAN_ERRORS, get_catalog_cache, get_replan_planner
from larder_api.schemas import (
    CheaperOut,
    Currency,
    DiaryDayOut,
    DiaryOut,
    FoodLogRequest,
    MacrosOut,
    OutcomeOut,
    PriceItemOut,
    PricePointOut,
    PricesOut,
    RecapOut,
    RecentFoodItemOut,
    RecentFoodOut,
    RemovedLogOut,
    ReplanRequest,
    SpendingCategoryOut,
    SpendingOut,
    SpendingWeekOut,
    WeightIn,
    WeightOut,
)
from larder_api.settings import Settings, get_settings
from larder_core.meals import Slot
from larder_core.regions import local_today
from larder_db.models import (
    BodyProfile,
    BodyWeight,
    Food,
    Goals,
    MealLog,
    MealPlan,
    PlanMeal,
    Preferences,
)
from larder_llm.schemas import AteOffPlan, OffPlanItem, Swap, When

router = APIRouter(tags=["diary"])

MAX_DAYS = 92
_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": "no weigh-in that day"}
}


def day_status(
    kcal: int, kcal_min: float | None, kcal_max: float | None
) -> Literal["under", "on", "over"]:
    if kcal_min is not None and kcal < kcal_min:
        return "under"
    if kcal_max is not None and kcal > kcal_max:
        return "over"
    return "on"


@router.get("/diary", operation_id="getDiary")
async def get_diary(
    user: CurrentUser,
    session: Session,
    clock: Annotated[Clock, Depends(get_clock)],
    days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = 7,
    end: Annotated[date | None, Query(description="last day shown (default: today)")] = None,
) -> DiaryOut:
    """`days` days up to `end`, oldest first."""
    today = local_today(user.timezone, clock())
    last = end or today
    first = last - timedelta(days=days - 1)
    logs = await planning.active_logs(session, user.id, first, days)
    planned = await _planned_kcal(session, user.id, first, last)
    goals = await session.get(Goals, user.id)
    kcal_min = goals.kcal_min if goals else None
    kcal_max = goals.kcal_max if goals else None

    out: list[DiaryDayOut] = []
    for d in range(days):
        on = first + timedelta(days=d)
        mine = [log for log in logs if log.eaten_on == on]
        eaten = MacrosOut(
            kcal=sum(log.kcal for log in mine),
            protein_g=sum(log.protein_g for log in mine),
            fat_g=sum(log.fat_g for log in mine),
            carbs_g=sum(log.carbs_g for log in mine),
        )
        out.append(
            DiaryDayOut(
                date=on,
                eaten=eaten,
                logged=[planning.logged_out(log) for log in mine],
                planned_kcal=planned.get(on),
                status=day_status(eaten.kcal, kcal_min, kcal_max) if mine else None,
            )
        )
    past = [d for d in out if d.date < today and d.status is not None]
    return DiaryOut(
        days=out,
        today=today,
        kcal_min=kcal_min,
        kcal_max=kcal_max,
        protein_g_min=goals.protein_g_min if goals else None,
        logged_days=len(past),
        on_target_days=sum(d.status == "on" for d in past),
    )


async def _planned_kcal(session: Session, user_id: int, first: date, last: date) -> dict[date, int]:
    """Each date's planned energy in the newest plan version covering it."""
    plans = (
        await session.scalars(
            select(MealPlan)
            .where(MealPlan.user_id == user_id, MealPlan.start_date <= last)
            .order_by(MealPlan.id.desc())
            .limit(50)
        )
    ).all()
    owner: dict[date, int] = {}
    for plan in plans:
        for d in range(plan.days):
            on = plan.start_date + timedelta(days=d)
            if first <= on <= last:
                owner.setdefault(on, plan.id)
    if not owner:
        return {}
    meals = await session.execute(
        select(PlanMeal.plan_id, PlanMeal.day, PlanMeal.kcal).where(
            PlanMeal.plan_id.in_(set(owner.values()))
        )
    )
    starts = {p.id: p.start_date for p in plans}
    out = dict.fromkeys(owner, 0)
    for plan_id, day, kcal in meals:
        on = starts[plan_id] + timedelta(days=day)
        if owner.get(on) == plan_id:
            out[on] += kcal
    return out


RECENT_DAYS = 60
RECENT_SHOWN = 8


@router.get("/diary/recent", operation_id="listRecentFoods")
async def recent_foods(
    user: CurrentUser, session: Session, clock: Annotated[Clock, Depends(get_clock)]
) -> list[RecentFoodOut]:
    """Food logged off-plan over the last RECENT_DAYS days with exact foods and amounts, newest
    first, each mix once (at most RECENT_SHOWN): what quick-add offers to log again."""
    since = local_today(user.timezone, clock()) - timedelta(days=RECENT_DAYS)
    logs = await session.scalars(
        select(MealLog)
        .where(
            MealLog.user_id == user.id,
            MealLog.kind == "off_plan",
            MealLog.voided_at.is_(None),
            MealLog.eaten_on >= since,
        )
        .order_by(MealLog.eaten_on.desc(), MealLog.id.desc())
        .limit(200)
    )
    chosen: list[tuple[MealLog, list[tuple[int, float]]]] = []
    seen: set[tuple[tuple[int, int], ...]] = set()
    for log in logs:
        items = [(i.get("food_id"), i.get("grams")) for i in log.items]
        picks = [(int(f), float(g)) for f, g in items if f is not None and g]
        if not picks or len(picks) != len(items):
            continue  # estimated without exact foods: nothing to log again
        key = tuple(sorted((f, round(g)) for f, g in picks))
        if key not in seen:
            seen.add(key)
            chosen.append((log, picks))
        if len(chosen) == RECENT_SHOWN:
            break
    ids = {f for _, picks in chosen for f, _ in picks}
    foods = {f.id: f for f in await session.scalars(select(Food).where(Food.id.in_(ids)))}
    return [
        RecentFoodOut(
            description=log.description,
            kcal=log.kcal,
            last_eaten_on=log.eaten_on,
            items=[RecentFoodItemOut(food=summary(foods[f]), grams=g) for f, g in picks],
        )
        for log, picks in chosen
        if all(f in foods for f, _ in picks)
    ]


@router.get("/me/weights", operation_id="listWeights")
async def list_weights(
    user: CurrentUser,
    session: Session,
    clock: Annotated[Clock, Depends(get_clock)],
    days: Annotated[int, Query(ge=1, le=730)] = 90,
) -> list[WeightOut]:
    """Weigh-ins of the last `days` days, oldest first."""
    since = local_today(user.timezone, clock()) - timedelta(days=days - 1)
    rows = await session.scalars(
        select(BodyWeight)
        .where(BodyWeight.user_id == user.id, BodyWeight.measured_on >= since)
        .order_by(BodyWeight.measured_on)
    )
    return [WeightOut.model_validate(r) for r in rows]


@router.put("/me/weights", operation_id="putWeight")
async def put_weight(
    body: WeightIn,
    user: CurrentUser,
    session: Session,
    clock: Annotated[Clock, Depends(get_clock)],
) -> WeightOut:
    """Record (or replace) the weigh-in of a day, at most a day ahead of the user's today."""
    if body.measured_on > local_today(user.timezone, clock()) + timedelta(days=1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, ["A weigh-in can't be in the future."])
    weight = round(body.weight_kg, 1)
    await session.execute(
        insert(BodyWeight)
        .values(user_id=user.id, measured_on=body.measured_on, weight_kg=weight)
        .on_conflict_do_update(
            index_elements=[BodyWeight.user_id, BodyWeight.measured_on],
            set_={"weight_kg": weight},
        )
    )
    await _sync_profile(session, user.id)
    await session.commit()
    return WeightOut(measured_on=body.measured_on, weight_kg=weight)


@router.delete(
    "/me/weights/{measured_on}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteWeight",
    responses=_NOT_FOUND,
)
async def delete_weight(measured_on: date, user: CurrentUser, session: Session) -> Response:
    gone = await session.execute(
        delete(BodyWeight)
        .where(BodyWeight.user_id == user.id, BodyWeight.measured_on == measured_on)
        .returning(BodyWeight.measured_on)
    )
    if gone.first() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no weigh-in that day")
    await _sync_profile(session, user.id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _sync_profile(session: Session, user_id: int) -> None:
    """The body profile (if set up) takes the newest weigh-in's weight."""
    newest = await session.scalar(
        select(BodyWeight.weight_kg)
        .where(BodyWeight.user_id == user_id)
        .order_by(BodyWeight.measured_on.desc())
        .limit(1)
    )
    profile = await session.get(BodyProfile, user_id)
    if profile is not None and newest is not None:
        profile.weight_kg = newest


_LOG_ERRORS: dict[int | str, dict[str, Any]] = {
    **REPLAN_ERRORS,
    status.HTTP_404_NOT_FOUND: {"description": "a food doesn't exist"},
}


@router.post(
    "/diary/log",
    operation_id="logFood",
    responses=_LOG_ERRORS,
    dependencies=[Depends(per_user("diary_log"))],
)
async def log_food(
    body: FoodLogRequest,
    response: Response,
    user: CurrentUser,
    session: Session,
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    cache: Annotated[planning.CatalogCache, Depends(get_catalog_cache)],
    planner: Annotated[planning.Planner, Depends(get_replan_planner)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> OutcomeOut:
    """Log food the user picked (search or barcode) with exact grams. It goes through the same
    executor as food eaten off-plan, so it counts toward the day and the rest of that day's
    plan rebalances around it; nutrition comes from the food data, never a guess."""
    ids = {i.food_id for i in body.items}
    found = {f.id: f for f in await session.scalars(select(Food).where(Food.id.in_(ids)))}
    if missing := ids - found.keys():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no food {min(missing)}")
    picks = [(found[i.food_id], i.grams) for i in body.items]
    names = [short_name(f.description) for f, _ in picks]
    change = AteOffPlan(
        intent="ate_off_plan",
        when=When(date=body.eaten_on, slot=body.slot),
        description=", ".join(dict.fromkeys(names)).capitalize(),
        items=[OffPlanItem(name=short_name(f.description), quantity=f"{g:g} g") for f, g in picks],
    )
    request = ReplanRequest(
        changes=[change], client_id=body.client_id, today=body.today, local_time=body.local_time
    )
    timed = await replans.run(
        session,
        user.id,
        request,
        sessionmaker=sessionmaker,
        catalog=cache,
        planner=planner,
        settings=settings,
        now=clock(),
        estimates={0: offplan.exact(picks)},
    )
    response.headers["Server-Timing"] = timed.server_timing
    return OutcomeOut.model_validate(timed.outcome.model_dump())


@router.delete(
    "/diary/logs/{log_id}",
    operation_id="removeLog",
    dependencies=[Depends(per_user("diary_log"))],  # it can replan, like logging food
    responses={
        **REPLAN_ERRORS,
        status.HTTP_404_NOT_FOUND: {"description": "no such log (or not yours)"},
        status.HTTP_400_BAD_REQUEST: {"description": "a meal marked eaten: undo it on the plan"},
    },
)
async def remove_log(
    log_id: int,
    user: CurrentUser,
    session: Session,
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    cache: Annotated[planning.CatalogCache, Depends(get_catalog_cache)],
    planner: Annotated[planning.Planner, Depends(get_replan_planner)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> RemovedLogOut:
    """Remove food logged by mistake, or a skip: it stops counting. On today or later, the
    meal it stood for is planned again (a swap through the executor, so the day rebalances);
    a past day just loses it. A meal marked eaten is undone from the plan instead."""
    log = await session.scalar(
        select(MealLog).where(
            MealLog.id == log_id, MealLog.user_id == user.id, MealLog.voided_at.is_(None)
        )
    )
    if log is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, ["That entry isn't in your diary."])
    if log.kind == "eaten":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, ["Undo a meal marked eaten from your plan."]
        )
    now = clock()
    today = local_today(user.timezone, now)
    log.voided_at = now
    on, slot = log.eaten_on, log.slot
    await session.commit()
    prefs = await session.get(Preferences, user.id)
    planned = slot is not None and planning.meal_modes(prefs)[Slot(slot)] == "plan"
    latest = await planning.latest_plan(session, user.id)
    covered = latest is not None and 0 <= (on - latest.start_date).days < latest.days
    if not planned or on < today or not covered:
        return RemovedLogOut()
    assert slot is not None
    swap = Swap(intent="swap", when=When(date=on, slot=Slot(slot)))
    request = ReplanRequest(changes=[swap], client_id=uuid.uuid4(), today=today)
    timed = await replans.run(
        session,
        user.id,
        request,
        sessionmaker=sessionmaker,
        catalog=cache,
        planner=planner,
        settings=settings,
        now=now,
    )
    return RemovedLogOut(outcome=OutcomeOut.model_validate(timed.outcome.model_dump()))


MAX_WEEKS = 52


@router.get("/insights/spending", operation_id="getSpending")
async def spending(
    user: CurrentUser,
    session: Session,
    clock: Annotated[Clock, Depends(get_clock)],
    weeks: Annotated[int, Query(ge=1, le=MAX_WEEKS)] = 12,
) -> SpendingOut:
    """What the user spent on groceries (their confirmed receipts) per week, beside the plans'
    estimated food cost, and where the money went by food group."""
    this_week = monday(local_today(user.timezone, clock()))
    first = this_week - timedelta(weeks=weeks - 1)
    data = await weekly_spending(session, user.id, first, weeks)
    goals = await session.get(Goals, user.id)
    return SpendingOut(
        currency=cast(Currency, goals.currency) if goals is not None else "GBP",
        weeks=[
            SpendingWeekOut(start=w, spent_minor=v, planned_minor=data.planned.get(w))
            for w, v in data.spent.items()
        ],
        categories=[
            SpendingCategoryOut(category=c, spent_minor=v)
            for c, v in sorted(data.by_category.items(), key=lambda kv: -kv[1])
        ],
        unmatched_minor=data.unmatched,
    )


@router.get("/insights/recap", operation_id="getRecap")
async def recap(
    user: CurrentUser,
    session: Session,
    clock: Annotated[Clock, Depends(get_clock)],
    week: Annotated[
        date | None, Query(description="any day of the week (default: the last full week)")
    ] = None,
) -> RecapOut:
    """A week looked back on: meals, energy and protein, spending, weight, favourites and price
    rises. Weeks after this one have nothing to show."""
    today = local_today(user.timezone, clock())
    start = monday(week) if week else monday(today) - timedelta(weeks=1)
    if start > today:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, ["That week hasn't started yet."])
    return await weekly_recap(session, user, start, today)


@router.get("/insights/prices", operation_id="getPrices")
async def prices(
    user: CurrentUser,
    session: Session,
    clock: Annotated[Clock, Depends(get_clock)],
    months: Annotated[int, Query(ge=1, le=24)] = 6,
) -> PricesOut:
    """What the user pays per kg for the foods they buy again and again, from their confirmed
    receipts: rises, and a cheaper product they've bought for the same food (price_watch)."""
    today = local_today(user.timezone, clock())
    items = watch(await load_lines(session, user.id, today, months))
    goals = await session.get(Goals, user.id)
    return PricesOut(
        currency=cast(Currency, goals.currency) if goals is not None else "GBP",
        items=[
            PriceItemOut(
                food_id=i.food_id,
                name=i.name,
                history=[PricePointOut(on=on, per_kg_minor=p) for on, p in i.history],
                latest_minor=i.latest,
                usual_minor=i.usual,
                change_pct=i.change_pct,
                rise=i.rise,
                cheaper=CheaperOut(
                    label=i.cheaper.label,
                    per_kg_minor=i.cheaper.per_kg,
                    last_bought=i.cheaper.last_bought,
                )
                if i.cheaper
                else None,
            )
            for i in items
        ],
    )
