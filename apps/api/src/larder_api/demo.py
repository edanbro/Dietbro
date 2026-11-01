"""The public demo account ("Try the demo" on the landing page). Visitors sign in as one shared
Clerk user (the web app mints a short-lived sign-in ticket for it); this module makes its data a
known, tidy starting point again every night: profile, goals, an Irish region and a pantry with
food expiring over the next days. No plan is made in advance: planning the week is the first
thing a visitor tries.

Guard rails: the demo account can't be deleted through the API, and it never calls a model (the
offline matchers stand in), so visitors never spend model credit. Anyone can sign in as it, so
nothing it holds may reach further than that account: it makes no share links (a public page on
our address, with whatever the last visitor typed), no calendar feed, and takes no reminders (one
visitor's browser would be told about the next visitor's plan).
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api.auth import CurrentUser
from larder_api.settings import Settings, get_settings
from larder_db import models as db

__all__ = ["DEMO_PANTRY", "is_demo", "not_for_demo", "reset_demo", "reset_if_stale"]

RESET_HOUR = 3  # UTC

# (food id, grams, days until it expires): generic USDA foods every import has.
DEMO_PANTRY: tuple[tuple[int, int, int | None], ...] = (
    (171077, 600, 2),  # chicken breast, raw
    (170026, 1500, 10),  # potatoes
    (170000, 500, 14),  # onions
    (171265, 1000, 4),  # whole milk
    (171287, 360, 12),  # eggs
    (173904, 500, None),  # oats
    (170393, 400, 6),  # carrots
    (168462, 200, 1),  # spinach
)


def is_demo(subject: str | None, demo_subject: str | None) -> bool:
    return bool(demo_subject) and subject == demo_subject


def not_for_demo(what: str) -> Callable[..., None]:
    """A route dependency: refuse the shared demo account, saying `what` isn't available."""

    def check(user: CurrentUser, settings: Annotated[Settings, Depends(get_settings)]) -> None:
        if is_demo(user.auth_subject, settings.demo_auth_subject):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, [f"{what} isn't available in the demo account."]
            )

    return check


def last_reset_time(now: datetime) -> datetime:
    """The latest RESET_HOUR at or before `now`."""
    today = now.replace(hour=RESET_HOUR, minute=0, second=0, microsecond=0)
    return today if now >= today else today - timedelta(days=1)


async def reset_if_stale(
    sessionmaker: async_sessionmaker[AsyncSession], subject: str, now: datetime
) -> bool:
    """Reset the demo account if it hasn't been since the last reset time. A host that sleeps is
    rarely awake at that minute, so this looks at the row's age rather than the clock."""
    async with sessionmaker() as session:
        created = await session.scalar(
            select(db.User.created_at).where(db.User.auth_subject == subject)
        )
    if created is not None and created >= last_reset_time(now):
        return False
    await reset_demo(sessionmaker, subject, now)
    return True


async def reset_demo(
    sessionmaker: async_sessionmaker[AsyncSession], subject: str, now: datetime | None = None
) -> int:
    """Delete the demo user's data (the user row cascades to everything they own) and set the
    starting point up again; returns the new user id."""
    today: date = (now or datetime.now(UTC)).date()
    async with sessionmaker() as session:
        await session.execute(delete(db.User).where(db.User.auth_subject == subject))
        user = db.User(auth_subject=subject, country="IE", timezone="Europe/Dublin")
        session.add(user)
        await session.flush()
        session.add_all(
            [
                db.Goals(
                    user_id=user.id,
                    goal="maintain",
                    kcal_min=1800,
                    kcal_max=2200,
                    calorie_floor=1200,
                    max_daily_deficit=1000,
                    protein_g_min=100,
                    weekly_budget_minor=7000,
                    currency="EUR",
                ),
                db.Allergies(user_id=user.id, allergens=[], avoid_food_ids=[]),
                db.Preferences(
                    user_id=user.id,
                    diet=None,
                    liked_cuisines=["Irish", "Italian"],
                    disliked_cuisines=[],
                    liked_food_ids=[],
                    disliked_food_ids=[],
                ),
            ]
        )
        known = set(
            await session.scalars(
                select(db.Food.id).where(db.Food.id.in_([f for f, _, _ in DEMO_PANTRY]))
            )
        )
        session.add_all(
            db.PantryItem(
                user_id=user.id,
                food_id=food_id,
                grams=grams,
                quantity=grams,
                unit="g",
                expires_on=today + timedelta(days=days) if days is not None else None,
                source="manual",
            )
            for food_id, grams, days in DEMO_PANTRY
            if food_id in known
        )
        await session.commit()
        return user.id
