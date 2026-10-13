"""Planned meals marked eaten, and undone (M5, docs/adr/0015-eaten-and-app-replans.md).

Marking (date, slot) of the user's current plan eaten, in one transaction under the per-user
plan lock (`planning.lock_user_plans`, which replans and POST /plans take too):

- Refused: a `today` more than a day from the server's UTC date (400), a date after `today`
  (400), a plan that isn't the user's (404) or isn't their latest version (409: reload), a
  date outside the plan or a cell with no meal (404).
- Already marked (an active `eaten` log for the cell): nothing changes (`changed=False`).
- Otherwise: other active logs for the cell (off-plan food, a skip) are voided; a MealLog
  kind="eaten", source "app", with the planned meal's macros (not an estimate) and recipe, is
  linked to the plan; the meal row's `status` becomes "eaten" in place (no new version: the
  meal and the day's totals are unchanged). Replans count the log as fixed intake and keep the
  slot empty (chat/replan.py), carrying the eaten row over.
- Pantry: per food, the planner's grams per portion (`planning.portion_grams`: staples and
  unresolved lines take nothing) x the row's portions are taken from the user's pantry items
  of that food whose quantity converts to grams (larder_core.units/quantities; others are
  skipped), soonest-expiring first (undated last, then by id), never below zero. Approximate
  items are taken from like any other: the planner counts their grams as stock. Items that
  reach zero are kept (at 0) so undo can refill them. What was taken (item id, grams, quantity
  in the item's own unit) is stored on the log (`pantry_taken`).

Undo voids the active eaten log, sets the row back to "planned" and gives back exactly what was
taken: grams and quantity (if the user changed the item's unit since, the quantity follows the
item's own grams per unit). Items deleted since are not recreated (`remaining_quantity` null).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_api.routers.foods import food_portions
from larder_api.schemas import EatenOut, PantryChangeOut
from larder_core.meals import Slot
from larder_core.quantities import grams_for
from larder_core.units import parse_measure
from larder_db import models as db

BAD_TODAY = "Your device's date looks wrong - please check it and try again."
_EPSILON = 1e-9

# --- the pantry arithmetic (pure) -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Line:
    """A recipe ingredient line: its food (None = unresolved), grams for the whole recipe."""

    food_id: int | None
    grams: float | None
    staple: bool


@dataclass(frozen=True, slots=True)
class Stock:
    """A pantry item as `take` sees it. `convertible`: its quantity converts to grams."""

    item_id: int
    food_id: int
    grams: float
    quantity: float
    unit: str
    expires_on: date | None
    convertible: bool


@dataclass(frozen=True, slots=True)
class Taken:
    """What one pantry item gave to a meal: grams and the same amount in the item's unit."""

    item_id: int
    food_id: int
    grams: float
    quantity: float
    unit: str

    def as_json(self) -> dict[str, Any]:
        return {
            "pantry_item_id": self.item_id,
            "food_id": self.food_id,
            "grams": self.grams,
            "quantity": self.quantity,
            "unit": self.unit,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Taken":
        return cls(
            int(data["pantry_item_id"]),
            int(data["food_id"]),
            float(data["grams"]),
            float(data["quantity"]),
            str(data["unit"]),
        )


def meal_needs(lines: Iterable[Line], *, servings: int, portions: int) -> dict[int, float]:
    """Grams per food for `portions` half-servings, as the planner counts them."""
    if servings <= 0:
        return {}
    out: dict[int, float] = {}
    for line in lines:
        if line.food_id is None:
            continue
        grams = planning.portion_grams(line.grams, servings, line.staple) * portions
        if grams > 0:
            out[line.food_id] = out.get(line.food_id, 0) + grams
    return out


def take(needs: Mapping[int, float], stock: Sequence[Stock]) -> list[Taken]:
    """Each food's need from its convertible, non-empty items, soonest-expiring first (undated
    last, ties by id), never more than an item holds. Taking all of an item takes exactly its
    quantity; part of it, the same share of its quantity."""
    order = sorted(
        (s for s in stock if s.convertible and s.grams > 0 and s.quantity > 0),
        key=lambda s: (s.expires_on is None, s.expires_on or date.max, s.item_id),
    )
    out: list[Taken] = []
    for food_id in sorted(needs):
        left = needs[food_id]
        for s in order:
            if left <= _EPSILON:
                break
            if s.food_id != food_id:
                continue
            if left >= s.grams:
                grams, quantity = s.grams, s.quantity
            else:
                grams, quantity = left, s.quantity * left / s.grams
            out.append(Taken(s.item_id, food_id, grams, quantity, s.unit))
            left -= grams
    return out


def give_back(
    grams: float,
    quantity: float,
    unit: str,
    taken: Taken,
    *,
    grams_per_unit: float | None = None,
) -> tuple[float, float]:
    """An item's (grams, quantity) after `taken` comes back. Same unit: both add up. The unit
    changed since: the quantity follows the item's own grams per unit, or `grams_per_unit` (its
    conversion) when the item is empty; without either only the grams come back."""
    new_grams = grams + taken.grams
    if unit == taken.unit:
        return new_grams, quantity + taken.quantity
    if grams > 0:
        return new_grams, quantity * new_grams / grams
    if grams_per_unit:
        return new_grams, new_grams / grams_per_unit
    return new_grams, quantity


# --- database ---------------------------------------------------------------------------------


def check_dates(on: date, today: date, now: datetime) -> None:
    if abs((today - now.astimezone(UTC).date()).days) > 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, [BAD_TODAY])
    if on > today:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, ["You can only mark a meal eaten on or after its day."]
        )


async def _plan(session: AsyncSession, user_id: int, plan_id: int, on: date) -> db.MealPlan:
    """The user's plan, which must be their latest version and cover `on`; read under the plan
    lock (taken here, held until the transaction ends)."""
    await planning.lock_user_plans(session, user_id)
    plan = await session.scalar(
        select(db.MealPlan)
        .where(db.MealPlan.id == plan_id, db.MealPlan.user_id == user_id)
        .options(
            selectinload(db.MealPlan.meals)
            .selectinload(db.PlanMeal.recipe)
            .selectinload(db.Recipe.ingredients)
        )
    )
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "plan not found")
    latest = await session.scalar(
        select(db.MealPlan.id)
        .where(db.MealPlan.user_id == user_id)
        .order_by(db.MealPlan.created_at.desc(), db.MealPlan.id.desc())
        .limit(1)
    )
    if latest != plan.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, ["Your plan has changed - reload it and try again."]
        )
    if not 0 <= (on - plan.start_date).days < plan.days:
        raise HTTPException(status.HTTP_404_NOT_FOUND, ["That day isn't in this plan."])
    return plan


def _row(plan: db.MealPlan, on: date, slot: Slot) -> db.PlanMeal | None:
    day = (on - plan.start_date).days
    return next((m for m in plan.meals if m.day == day and m.slot == slot), None)


async def _active(session: AsyncSession, user_id: int, on: date, slot: Slot) -> list[db.MealLog]:
    return list(
        await session.scalars(
            select(db.MealLog)
            .where(
                db.MealLog.user_id == user_id,
                db.MealLog.voided_at.is_(None),
                db.MealLog.eaten_on == on,
                db.MealLog.slot == slot.value,
            )
            .order_by(db.MealLog.id)
            .with_for_update()
        )
    )


async def _items(
    session: AsyncSession, user_id: int, ids: Iterable[int]
) -> dict[int, db.PantryItem]:
    rows = await session.scalars(
        select(db.PantryItem)
        .where(db.PantryItem.user_id == user_id, db.PantryItem.id.in_(set(ids)))
        .options(selectinload(db.PantryItem.food))
        .with_for_update()
    )
    return {i.id: i for i in rows}


async def _converts(session: AsyncSession, item: db.PantryItem, quantity: float) -> float | None:
    """Grams of `quantity` of the item in its unit (larder_core), None if it doesn't convert."""
    measure = parse_measure(f"{quantity:g} {item.unit}")
    grams = grams_for(
        measure,
        await food_portions(session, item.food),
        item.food.description.lower(),
        item.food.category,
    )
    return None if grams is None or measure.vague else grams


async def _give_back(
    session: AsyncSession, user_id: int, taken: Sequence[Taken]
) -> dict[int, db.PantryItem]:
    """Put `taken` back into the user's pantry items that still exist (returned by id)."""
    items = await _items(session, user_id, (t.item_id for t in taken))
    for t in taken:
        item = items.get(t.item_id)
        if item is None:
            continue
        per_unit = None
        if item.grams <= 0 and item.unit != t.unit:
            per_unit = await _converts(session, item, 1)
        item.grams, item.quantity = give_back(
            item.grams, item.quantity, item.unit, t, grams_per_unit=per_unit
        )
    return items


async def give_back_logs(
    session: AsyncSession,
    user_id: int,
    voided: Iterable[db.MealLog],
    latest: db.MealPlan | None,
) -> None:
    """Eaten logs a replan voided (the user reported that meal otherwise in the chat): their
    pantry food goes back, and the latest plan's row is no longer shown eaten. The caller sets
    `voided_at` and commits."""
    for log in voided:
        if log.kind != "eaten":
            continue
        await _give_back(session, user_id, [Taken.from_json(t) for t in log.pantry_taken])
        if latest is not None and log.slot is not None:
            await session.execute(
                update(db.PlanMeal)
                .where(
                    db.PlanMeal.plan_id == latest.id,
                    db.PlanMeal.day == (log.eaten_on - latest.start_date).days,
                    db.PlanMeal.slot == log.slot,
                )
                .values(status="planned")
            )


def shown_as_meals(logs: Iterable[db.MealLog], plan: db.MealPlan | None) -> set[int]:
    """Ids of the eaten logs whose meal `plan` still plans (same cell, same recipe): a version
    copied from `plan` carries that row (status eaten) instead of listing the log."""
    if plan is None:
        return set()
    rows = {(plan.start_date + timedelta(days=m.day), m.slot): m.recipe_id for m in plan.meals}
    return {
        log.id
        for log in logs
        if log.kind == "eaten"
        and log.slot is not None
        and log.recipe_id is not None
        and rows.get((log.eaten_on, log.slot)) == log.recipe_id
    }


def _change(taken: Taken, item: db.PantryItem | None) -> PantryChangeOut:
    return PantryChangeOut(
        pantry_item_id=taken.item_id,
        food_id=taken.food_id,
        name=item.food.description if item is not None else "",
        grams=round(taken.grams, 1),
        quantity=round(taken.quantity, 2),
        unit=taken.unit,
        remaining_quantity=round(item.quantity, 2) if item is not None else None,
    )


def _out(
    plan: db.MealPlan,
    on: date,
    slot: Slot,
    row: db.PlanMeal | None,
    *,
    eaten: bool,
    changed: bool,
    pantry: list[PantryChangeOut],
    notes: list[str] | None = None,
) -> EatenOut:
    return EatenOut(
        plan_id=plan.id,
        date=on,
        slot=slot,
        status="eaten" if eaten else "planned",
        changed=changed,
        meal=planning.meal_out(row) if row is not None else None,
        pantry=pantry,
        notes=notes or [],
    )


async def mark(
    session: AsyncSession, user_id: int, plan_id: int, on: date, slot: Slot, now: datetime
) -> EatenOut:
    plan = await _plan(session, user_id, plan_id, on)
    row = _row(plan, on, slot)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, [f"There's no meal planned for {on:%a} {slot}."]
        )
    active = await _active(session, user_id, on, slot)
    done = next((log for log in active if log.kind == "eaten"), None)
    if done is not None:
        taken = [Taken.from_json(t) for t in done.pantry_taken]
        items = await _items(session, user_id, (t.item_id for t in taken))
        row.status = "eaten"  # repairs a row copied before the mark
        await session.commit()
        pantry = [_change(t, items.get(t.item_id)) for t in taken]
        return _out(plan, on, slot, row, eaten=True, changed=False, pantry=pantry)

    for log in active:  # a new log for a meal replaces what was logged for it before
        log.voided_at = now
    recipe = row.recipe
    _, info = await planning.load_foods(
        session, (line.food_id for line in recipe.ingredients if line.food_id is not None)
    )
    needs = meal_needs(
        (
            Line(line.food_id, line.grams, line.food_id is not None and info[line.food_id].staple)
            for line in recipe.ingredients
        ),
        servings=recipe.servings or 0,
        portions=row.portions,
    )
    pantry_rows = (
        await session.scalars(
            select(db.PantryItem)
            .join(db.Food, db.Food.id == db.PantryItem.food_id)
            .where(
                db.PantryItem.user_id == user_id,
                # A product or regional food counts as the generic food the recipe uses.
                func.coalesce(db.Food.generic_food_id, db.PantryItem.food_id).in_(needs),
            )
            .options(selectinload(db.PantryItem.food))
            .with_for_update(of=db.PantryItem)
        )
    ).all()
    items = {i.id: i for i in pantry_rows}
    stock: list[Stock] = []
    for i in pantry_rows:
        convertible = i.grams > 0 and i.quantity > 0
        if convertible:
            convertible = await _converts(session, i, i.quantity) is not None
        key = planning.pantry_key(i, needs)
        stock.append(Stock(i.id, key, i.grams, i.quantity, i.unit, i.expires_on, convertible))
    taken = take(needs, stock)
    for t in taken:
        item = items[t.item_id]
        if t.grams >= item.grams:
            item.grams, item.quantity = 0.0, 0.0
        else:
            item.grams = max(0.0, item.grams - t.grams)
            item.quantity = max(0.0, item.quantity - t.quantity)
    session.add(
        db.MealLog(
            user_id=user_id,
            eaten_on=on,
            slot=slot.value,
            kind="eaten",
            description=recipe.name,
            kcal=row.kcal,
            protein_g=row.protein_g,
            fat_g=row.fat_g,
            carbs_g=row.carbs_g,
            estimated=False,
            items=[],
            source="app",
            recipe_id=recipe.id,
            plan_id=plan.id,
            pantry_taken=[t.as_json() for t in taken],
        )
    )
    row.status = "eaten"
    await session.commit()
    pantry = [_change(t, items[t.item_id]) for t in taken]
    return _out(plan, on, slot, row, eaten=True, changed=True, pantry=pantry)


async def unmark(
    session: AsyncSession, user_id: int, plan_id: int, on: date, slot: Slot, now: datetime
) -> EatenOut:
    plan = await _plan(session, user_id, plan_id, on)
    row = _row(plan, on, slot)
    active = await _active(session, user_id, on, slot)
    log = next((x for x in active if x.kind == "eaten"), None)
    if log is None:
        if row is not None and row.status == "eaten":
            row.status = "planned"  # a row copied while a mark was being undone
            await session.commit()
        return _out(plan, on, slot, row, eaten=False, changed=False, pantry=[])

    log.voided_at = now
    taken = [Taken.from_json(t) for t in log.pantry_taken]
    items = await _give_back(session, user_id, taken)
    if row is not None:
        row.status = "planned"
    await session.commit()
    pantry = [_change(t, items.get(t.item_id)) for t in taken]
    gone = sum(1 for t in taken if t.item_id not in items)
    notes: list[str] = []
    if gone:
        what = "a pantry item it used was" if gone == 1 else f"{gone} pantry items it used were"
        notes.append(f"Undone, but {what} deleted since, so nothing was put back there.")
    return _out(plan, on, slot, row, eaten=False, changed=True, pantry=pantry, notes=notes)
