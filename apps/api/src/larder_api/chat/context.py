"""The per-turn context block (larder_llm.prompts.TurnContext) from the database: the current
plan from today to its end only (dates, meals with recipe ids, kcal per day, logged meals),
targets, allergies and avoided foods by name, diet, budget, and up to 8 pantry items expiring
within 5 days. Kept to about 400 tokens: every copy is replayed in later turns of the epoch."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_api.chat.scope import ChatScope
from larder_api.schemas import MealLogOut
from larder_core.allergens import LABELS, Allergen
from larder_core.meals import SLOT_ORDER, Slot
from larder_db import models as db
from larder_llm.prompts import DayLine, MealLine, TurnContext

EXPIRING_DAYS = 5
MAX_EXPIRING = 8
SYMBOLS = {"GBP": "£", "EUR": "€", "USD": "$"}


def money(minor: int, currency: str) -> str:
    symbol = SYMBOLS.get(currency)
    amount = f"{minor / 100:,.2f}"
    return f"{symbol}{amount}" if symbol else f"{amount} {currency}"


def short_name(description: str) -> str:
    """'Mushrooms, white, raw' -> 'mushrooms': USDA descriptions are long."""
    return description.split(",", 1)[0].strip().lower()


async def latest_plan(session: AsyncSession, user_id: int, on: date) -> db.MealPlan | None:
    """The plan in force on `on` (planning.plan_id_for) with its meals' recipes loaded."""
    plan_id = await planning.plan_id_for(session, user_id, on)
    if plan_id is None:
        return None
    return await session.scalar(
        select(db.MealPlan)
        .where(db.MealPlan.id == plan_id)
        .options(selectinload(db.MealPlan.meals).selectinload(db.PlanMeal.recipe))
    )


def plan_stats(plan: db.MealPlan) -> planning.PlanStats | None:
    try:
        return planning.PlanStats.model_validate(plan.stats)
    except ValueError:
        return None


def logged_line(entry: MealLogOut) -> str:
    """'lunch: pizza (~850 kcal, off-plan)', 'dinner: skipped', 'lunch: Dal (~600 kcal, eaten)'."""
    where = f"{entry.slot}: " if entry.slot else ""
    if entry.kind == "eaten":
        return f"{where}{entry.description} (~{entry.kcal} kcal, eaten)"
    if entry.kind == "skipped":
        counted = f" (~{entry.kcal} kcal eaten elsewhere)" if entry.kcal else ""
        return f"{where}skipped{counted}"
    return f"{where}{entry.description} (~{entry.kcal} kcal, off-plan)"


def day_lines(plan: db.MealPlan, today: date) -> tuple[DayLine, ...]:
    """The plan's days from `today` on (past days are never re-planned)."""
    stats = plan_stats(plan)
    lines: list[DayLine] = []
    for day in range(plan.days):
        on = plan.start_date + timedelta(days=day)
        if on < today:
            continue
        meals = sorted(
            (m for m in plan.meals if m.day == day), key=lambda m: SLOT_ORDER.index(Slot(m.slot))
        )
        logged = stats.logged_on(day) if stats else []
        totals = stats.day_totals if stats else []
        kcal = totals[day].kcal if day < len(totals) else sum(m.kcal for m in meals)
        lines.append(
            DayLine(
                date=on,
                meals=tuple(
                    MealLine(
                        Slot(m.slot),
                        m.recipe_id,
                        m.recipe.name + (" (eaten)" if m.status == "eaten" else ""),
                        m.portions / 2,
                        m.kcal,
                    )
                    for m in meals
                ),
                kcal=kcal,
                logged=tuple(logged_line(entry) for entry in logged),
            )
        )
    return tuple(lines)


async def turn_context(scope: ChatScope) -> TurnContext:
    async with scope.sessionmaker() as session:
        goals = await session.get(db.Goals, scope.user_id)
        allergies = await session.get(db.Allergies, scope.user_id)
        preferences = await session.get(db.Preferences, scope.user_id)
        plan = await latest_plan(session, scope.user_id, scope.today)
        avoided: list[str] = (
            list(
                await session.scalars(
                    select(db.Food.description).where(db.Food.id.in_(allergies.avoid_food_ids))
                )
            )
            if allergies and allergies.avoid_food_ids
            else []
        )
        expiring = (
            await session.scalars(
                select(db.PantryItem)
                .where(
                    db.PantryItem.user_id == scope.user_id,
                    db.PantryItem.expires_on >= scope.today,
                    db.PantryItem.expires_on <= scope.today + timedelta(days=EXPIRING_DAYS),
                )
                .order_by(db.PantryItem.expires_on, db.PantryItem.id)
                .limit(MAX_EXPIRING)
                .options(selectinload(db.PantryItem.food))
            )
        ).all()
        days = day_lines(plan, scope.today) if plan else ()
    return TurnContext(
        today=scope.today,
        plan_id=plan.id if plan else None,
        days=days,
        kcal_min=round(goals.kcal_min) if goals else 0,
        kcal_max=round(goals.kcal_max) if goals else 0,
        calorie_floor=round(goals.calorie_floor) if goals else 0,
        protein_g_min=round(goals.protein_g_min) if goals and goals.protein_g_min else None,
        weekly_budget=(
            money(goals.weekly_budget_minor, goals.currency)
            if goals and goals.weekly_budget_minor
            else None
        ),
        allergens=tuple(LABELS[Allergen(a)] for a in allergies.allergens) if allergies else (),
        avoided_foods=tuple(dict.fromkeys(short_name(d) for d in avoided)),
        diet=preferences.diet if preferences else None,
        expiring=tuple(
            f"{short_name(p.food.description)} {p.quantity:g} {p.unit}, expires "
            f"{p.expires_on:%a %d %b}"
            for p in expiring
            if p.expires_on is not None
        ),
    )
