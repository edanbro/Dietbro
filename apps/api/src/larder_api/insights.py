"""Looking back: weekly grocery spending (GET /insights/spending) and the weekly recap (GET
/insights/recap, and the Sunday push in larder_api.reminders).

The recap only reports what happened: meals marked eaten, skipped or logged off-plan (the meal
logs), the days' energy and protein against the goals, money spent on confirmed receipts against
the budget and the plans' estimate, weigh-ins, the recipes eaten most and prices that went up
(larder_api.price_watch). Nothing is stored for it.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from larder_api import planning
from larder_api.price_watch import load_lines, watch
from larder_api.schemas import Currency, RecapOut, RecapRiseOut, RecapTopOut, RecipeCard
from larder_db import models as db

__all__ = ["Spending", "monday", "weekly_recap", "weekly_spending"]

# Receipt lines that went into the pantry (not rejected), as in larder_api.prices.
_KEPT = ("suggested", "accepted", "edited")


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


@dataclass(slots=True)
class Spending:
    spent: dict[date, int]  # per week (its Monday), every week in the window
    planned: dict[date, int] = field(default_factory=dict[date, int])  # the plans' estimate
    by_category: dict[str | None, int] = field(default_factory=dict[str | None, int])
    unmatched: int = 0  # spent on lines matched to no food


async def weekly_spending(session: AsyncSession, user_id: int, first: date, weeks: int) -> Spending:
    """Confirmed receipts per week from the Monday `first`, beside the newest version of each
    plan starting in those weeks (its estimated food cost)."""
    generic = aliased(db.Food)
    rows = (
        await session.execute(
            select(
                db.ReceiptUpload.purchased_on,
                db.ReceiptLine.price_minor,
                db.ReceiptLine.food_id,
                func.coalesce(generic.category, db.Food.category),
            )
            .join(db.ReceiptUpload, db.ReceiptLine.upload_id == db.ReceiptUpload.id)
            .outerjoin(db.Food, db.ReceiptLine.food_id == db.Food.id)
            .outerjoin(generic, db.Food.generic_food_id == generic.id)
            .where(
                db.ReceiptUpload.user_id == user_id,
                db.ReceiptUpload.status == "confirmed",
                db.ReceiptUpload.purchased_on >= first,
                db.ReceiptUpload.purchased_on < first + timedelta(weeks=weeks),
                db.ReceiptLine.status.in_(_KEPT),
                db.ReceiptLine.price_minor > 0,
            )
        )
    ).all()
    out = Spending(spent=dict.fromkeys((first + timedelta(weeks=i) for i in range(weeks)), 0))
    for bought, price, food_id, category in rows:
        week = monday(bought)
        if week not in out.spent or price is None:
            continue
        out.spent[week] += price
        if food_id is None:
            out.unmatched += price
        else:
            out.by_category[category] = out.by_category.get(category, 0) + price

    latest = (
        select(db.MealPlan.start_date, func.max(db.MealPlan.version).label("version"))
        .where(db.MealPlan.user_id == user_id, db.MealPlan.start_date >= first)
        .group_by(db.MealPlan.start_date)
        .subquery()
    )
    plans = await session.execute(
        select(db.MealPlan.start_date, db.MealPlan.stats)
        .join(
            latest,
            (db.MealPlan.start_date == latest.c.start_date)
            & (db.MealPlan.version == latest.c.version),
        )
        .where(db.MealPlan.user_id == user_id)
    )
    for start, stats in plans:
        cost = stats.get("cost_minor")
        if isinstance(cost, int) and monday(start) in out.spent:
            out.planned[monday(start)] = out.planned.get(monday(start), 0) + cost
    return out


TOP = 3


async def weekly_recap(session: AsyncSession, user: db.User, week: date, today: date) -> RecapOut:
    """The week from the Monday `week` (to its Sunday, or to `today` if that is earlier)."""
    first = monday(week)
    last = first + timedelta(days=6)
    goals = await session.get(db.Goals, user.id)

    planned = len(await planning.week_cells(session, user.id, first))
    logs = await planning.active_logs(session, user.id, first, 7)
    kinds = Counter(planning.log_kind(log) for log in logs)

    by_day: dict[date, list[db.MealLog]] = {}
    for log in logs:
        by_day.setdefault(log.eaten_on, []).append(log)
    kcal = {d: sum(log.kcal for log in mine) for d, mine in by_day.items()}
    protein = {d: sum(log.protein_g for log in mine) for d, mine in by_day.items()}
    kcal_min = goals.kcal_min if goals else None
    kcal_max = goals.kcal_max if goals else None
    protein_min = goals.protein_g_min if goals else None
    on_target = sum(
        (kcal_min is None or k >= kcal_min) and (kcal_max is None or k <= kcal_max)
        for k in kcal.values()
    )

    spending = await weekly_spending(session, user.id, first, 1)

    weights = list(
        await session.scalars(
            select(db.BodyWeight)
            .where(
                db.BodyWeight.user_id == user.id,
                db.BodyWeight.measured_on >= first,
                db.BodyWeight.measured_on <= last,
            )
            .order_by(db.BodyWeight.measured_on)
        )
    )
    change = round(weights[-1].weight_kg - weights[0].weight_kg, 1) if len(weights) >= 2 else None

    eaten = Counter(
        log.recipe_id
        for log in logs
        if planning.log_kind(log) == "eaten" and log.recipe_id is not None
    )
    top_ids = [rid for rid, _ in eaten.most_common(TOP)]
    recipes = {
        r.id: r for r in await session.scalars(select(db.Recipe).where(db.Recipe.id.in_(top_ids)))
    }

    rises = [
        RecapRiseOut(name=item.name, change_pct=item.change_pct)
        for item in watch(await load_lines(session, user.id, min(last, today), 6))
        if item.rise and first <= item.history[-1][0] <= last
    ]

    spent = spending.spent[first]
    return RecapOut(
        week_start=first,
        week_end=last,
        currency=cast(Currency, goals.currency) if goals is not None else "GBP",
        planned_meals=planned,
        eaten_meals=kinds["eaten"],
        skipped_meals=kinds["skipped"],
        off_plan=kinds["off_plan"],
        logged_days=len(by_day),
        avg_kcal=round(sum(kcal.values()) / len(kcal)) if kcal else None,
        kcal_min=kcal_min,
        kcal_max=kcal_max,
        on_target_days=on_target,
        protein_g_min=protein_min,
        protein_days=sum(p >= protein_min for p in protein.values())
        if protein_min is not None
        else None,
        spent_minor=spent,
        budget_minor=goals.weekly_budget_minor if goals else None,
        planned_cost_minor=spending.planned.get(first),
        weight_change_kg=change,
        weight_kg=weights[-1].weight_kg if weights else None,
        top_recipes=[
            RecapTopOut(
                recipe=RecipeCard.model_validate(recipes[rid], from_attributes=True),
                times=eaten[rid],
            )
            for rid in top_ids
            if rid in recipes
        ],
        price_rises=rises[:TOP],
        empty=not logs and not spent and not weights,
    )
