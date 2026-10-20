"""The food diary (what was eaten, day by day, against the goals) and weigh-ins.

Nothing new is stored for the diary: it reads the meal logs every replan already rebuilds
from (meals marked eaten, food logged off-plan, skips). Weigh-ins are one per day; the newest
is copied to the body profile so the energy targets follow the user's weight.
"""

from datetime import date, timedelta
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from larder_api import planning, replans
from larder_api.auth import CurrentUser
from larder_api.chat import offplan
from larder_api.chat.context import short_name
from larder_api.clock import Clock, get_clock
from larder_api.db import Session, get_sessionmaker
from larder_api.routers.plans import REPLAN_ERRORS, get_catalog_cache, get_replan_planner
from larder_api.schemas import (
    Currency,
    DiaryDayOut,
    DiaryOut,
    FoodLogRequest,
    MacrosOut,
    OutcomeOut,
    ReplanRequest,
    SpendingCategoryOut,
    SpendingOut,
    SpendingWeekOut,
    WeightIn,
    WeightOut,
)
from larder_api.settings import Settings, get_settings
from larder_core.regions import local_today
from larder_db.models import (
    BodyProfile,
    BodyWeight,
    Food,
    Goals,
    MealPlan,
    PlanMeal,
    ReceiptLine,
    ReceiptUpload,
)
from larder_llm.schemas import AteOffPlan, OffPlanItem, When

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


@router.post("/diary/log", operation_id="logFood", responses=_LOG_ERRORS)
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
    executor as "I had X" in the chat, so it counts toward the day and the rest of that day's
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


MAX_WEEKS = 52
# Receipt lines that went into the pantry (not rejected), as in larder_api.prices.
_KEPT = ("suggested", "accepted", "edited")


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


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
    generic = aliased(Food)
    rows = (
        await session.execute(
            select(
                ReceiptUpload.purchased_on,
                ReceiptLine.price_minor,
                ReceiptLine.food_id,
                func.coalesce(generic.category, Food.category),
            )
            .join(ReceiptUpload, ReceiptLine.upload_id == ReceiptUpload.id)
            .outerjoin(Food, ReceiptLine.food_id == Food.id)
            .outerjoin(generic, Food.generic_food_id == generic.id)
            .where(
                ReceiptUpload.user_id == user.id,
                ReceiptUpload.status == "confirmed",
                ReceiptUpload.purchased_on >= first,
                ReceiptLine.status.in_(_KEPT),
                ReceiptLine.price_minor > 0,
            )
        )
    ).all()
    spent = dict.fromkeys((first + timedelta(weeks=i) for i in range(weeks)), 0)
    by_category: dict[str | None, int] = {}
    unmatched = 0
    for bought, price, food_id, category in rows:
        week = monday(bought)
        if week not in spent or price is None:
            continue
        spent[week] += price
        if food_id is None:
            unmatched += price
        else:
            by_category[category] = by_category.get(category, 0) + price

    # The latest version of each plan (per start date) starting in the window.
    latest = (
        select(MealPlan.start_date, func.max(MealPlan.version).label("version"))
        .where(MealPlan.user_id == user.id, MealPlan.start_date >= first)
        .group_by(MealPlan.start_date)
        .subquery()
    )
    plans = await session.execute(
        select(MealPlan.start_date, MealPlan.stats)
        .join(
            latest,
            (MealPlan.start_date == latest.c.start_date) & (MealPlan.version == latest.c.version),
        )
        .where(MealPlan.user_id == user.id)
    )
    planned: dict[date, int] = {}
    for start, stats in plans:
        cost = stats.get("cost_minor")
        if isinstance(cost, int) and monday(start) in spent:
            planned[monday(start)] = planned.get(monday(start), 0) + cost

    goals = await session.get(Goals, user.id)
    return SpendingOut(
        currency=cast(Currency, goals.currency) if goals is not None else "GBP",
        weeks=[
            SpendingWeekOut(start=w, spent_minor=v, planned_minor=planned.get(w))
            for w, v in spent.items()
        ],
        categories=[
            SpendingCategoryOut(category=c, spent_minor=v)
            for c, v in sorted(by_category.items(), key=lambda kv: -kv[1])
        ],
        unmatched_minor=unmatched,
    )
