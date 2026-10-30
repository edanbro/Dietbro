"""The private calendar feed: planned meals as events in the user's own calendar app.

Calendar apps subscribe to a URL and can't sign in, so the URL carries a secret token
(/calendar/<token>.ics, 128 random bits). Resetting it makes a new address and the old one
stops working; turning it off removes it. The feed covers last week to two weeks ahead, from
the plan in force on each day, so swaps and replans show up on the calendar's next refresh.
It holds meal names, kcal and ingredients only.
"""

import re
import secrets
from datetime import UTC, time, timedelta
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_api.auth import CurrentUser
from larder_api.clock import Clock, get_clock
from larder_api.db import Session
from larder_api.ratelimit import per_ip, per_path
from larder_api.schemas import CalendarOut, CalendarTimes
from larder_api.settings import Settings, get_settings
from larder_core.brand import APP_NAME
from larder_core.ical import CalendarMeal, calendar
from larder_core.meals import SLOT_ORDER
from larder_core.regions import local_today
from larder_db import models as db

router = APIRouter(tags=["calendar"])

DEFAULT_TIMES = CalendarTimes()
MINUTES = {
    "breakfast": 20,
    "morning_snack": 10,
    "lunch": 30,
    "snack": 10,
    "dinner": 45,
    "evening_snack": 10,
}
DAYS_BEFORE, DAYS_AFTER = 7, 14
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,32}$")
_GONE: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": "no such feed (turned off or reset)"}
}


def _times(user: db.User) -> CalendarTimes:
    try:
        return CalendarTimes.model_validate(user.calendar_times or {})
    except ValueError:
        return DEFAULT_TIMES


def _out(user: db.User) -> CalendarOut:
    token = user.calendar_token
    return CalendarOut(
        enabled=token is not None,
        path=f"/calendar/{token}.ics" if token else None,
        times=_times(user),
    )


@router.get("/me/calendar", operation_id="getCalendar")
async def get_calendar(user: CurrentUser) -> CalendarOut:
    return _out(user)


@router.post("/me/calendar", operation_id="resetCalendar")
async def reset_calendar(user: CurrentUser, session: Session) -> CalendarOut:
    """Turn the feed on with a new private address (the old one, if any, stops working)."""
    user.calendar_token = secrets.token_urlsafe(16)
    await session.commit()
    return _out(user)


@router.delete("/me/calendar", operation_id="disableCalendar")
async def disable_calendar(user: CurrentUser, session: Session) -> CalendarOut:
    user.calendar_token = None
    await session.commit()
    return _out(user)


@router.put("/me/calendar/times", operation_id="putCalendarTimes")
async def put_calendar_times(
    body: CalendarTimes, user: CurrentUser, session: Session
) -> CalendarOut:
    user.calendar_times = body.model_dump()
    await session.commit()
    return _out(user)


def _description(meal: db.PlanMeal, recipe: db.Recipe) -> str:
    servings = meal.portions / 2
    amount = f"{servings:g} serving" + ("" if servings == 1 else "s")
    names = [i.raw_name for i in sorted(recipe.ingredients, key=lambda i: i.position)]
    shown = ", ".join(names[:12]) + (", ..." if len(names) > 12 else "")
    return f"{meal.kcal:,} kcal, {amount}.\nIngredients: {shown}"


@router.get(
    "/calendar/{token}.ics",
    operation_id="getCalendarFeed",
    dependencies=[
        Depends(per_path("calendar_feed", "token")),
        Depends(per_ip("calendar_feed_ip")),
    ],
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}}, **_GONE},
)
async def calendar_feed(
    token: str,
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> Response:
    """The feed itself. No sign-in: the token in the address is the permission."""
    if not _TOKEN.match(token):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "feed not found")
    user = await session.scalar(select(db.User).where(db.User.calendar_token == token))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "feed not found")
    now = clock()
    today = local_today(user.timezone, now)
    times = _times(user).model_dump()
    web = settings.cors_origins[0].rstrip("/") if settings.cors_origins else ""

    plans: dict[int, db.MealPlan] = {}
    meals: list[CalendarMeal] = []
    for offset in range(-DAYS_BEFORE, DAYS_AFTER + 1):
        on = today + timedelta(days=offset)
        plan_id = await session.scalar(
            select(db.MealPlan.id)
            .where(db.MealPlan.user_id == user.id, planning.covering(on))
            .order_by(db.MealPlan.created_at.desc(), db.MealPlan.id.desc())
            .limit(1)
        )
        if plan_id is None:
            continue
        if plan_id not in plans:
            plan = await session.scalar(
                select(db.MealPlan)
                .where(db.MealPlan.id == plan_id)
                .options(
                    selectinload(db.MealPlan.meals)
                    .selectinload(db.PlanMeal.recipe)
                    .selectinload(db.Recipe.ingredients)
                )
            )
            assert plan is not None
            plans[plan_id] = plan
        plan = plans[plan_id]
        day = (on - plan.start_date).days
        for meal in sorted(
            (m for m in plan.meals if m.day == day), key=lambda m: SLOT_ORDER.index(m.slot)
        ):
            recipe = meal.recipe
            meals.append(
                CalendarMeal(
                    on=on,
                    slot=meal.slot,
                    starts=time.fromisoformat(times[meal.slot]),
                    minutes=MINUTES.get(meal.slot, 30),
                    title=f"{meal.slot.capitalize()}: {recipe.name}",
                    description=_description(meal, recipe),
                    url=f"{web}/recipes/{recipe.id}/cook?servings={meal.portions / 2:g}"
                    if web
                    else None,
                )
            )
    text = calendar(
        f"{APP_NAME} meals",
        meals,
        now=now.astimezone(UTC),
        domain=urlsplit(web).hostname or "mealwright",
    )
    return Response(
        content=text,
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "private, max-age=900", "X-Robots-Tag": "noindex"},
    )
