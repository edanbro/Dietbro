"""Planning service: database -> solver Problem -> planner -> independent validator -> saved plan.

The rules live in pure packages (larder_solver, larder_core); this module only gathers inputs,
converts units at the boundary and applies the outcome rules of docs/adr/0009-planning-contract.md:
a plan with a safety or structural violation is never saved, whatever planner made it.
"""

import asyncio
import logging
import math
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from hashlib import blake2b

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from larder_api.routers.profile import body_from_row
from larder_api.schemas import (
    BandOut,
    MacrosOut,
    NutrientBands,
    TargetsOut,
    ViolationOut,
)
from larder_core.allergens import Allergen
from larder_core.energy import Targets as GoalTargets
from larder_core.energy import tdee, validate_targets
from larder_core.meals import SLOT_ORDER, Slot, recipe_slots
from larder_core.prices import Currency, Price, convert, price
from larder_core.tagging import Diet, FoodTags, RecipeTags, make_line, recipe_tags, tag_food
from larder_db import models as db
from larder_solver import (
    SAFETY_CODES,
    STRUCTURAL_CODES,
    Band,
    Catalog,
    Code,
    Food,
    Ingredient,
    Lot,
    Macros,
    Nutrient,
    Plan,
    PlanResult,
    Problem,
    Profile,
    Recipe,
    Status,
    Targets,
    Violation,
    check_problem,
    diagnose,
    greedy,
    hard,
    score,
    shopping_list,
    solve,
    validate,
)
from larder_solver.candidates import TastePrefs
from larder_solver.candidates import select as select_candidates
from larder_solver.metrics import allocate, cost_millipence, day_totals, to_minor, waste_millipence

logger = logging.getLogger(__name__)

DAYS = 7
# Per-slot portion ranges (half-servings) and repeat caps: docs/adr/0010.
SLOT_RULES: dict[Slot, tuple[bool, int, int, int | None]] = {
    Slot.BREAKFAST: (True, 1, 3, 4),
    Slot.LUNCH: (True, 1, 4, None),
    Slot.DINNER: (True, 2, 4, None),
    Slot.SNACK: (False, 1, 2, 4),
}
# Daily macro bands are looser than the weekly budget they add up to (PLAN §6).
DAILY_MIN_FACTOR, DAILY_MAX_FACTOR = 0.8, 1.25
CATALOG_TTL_S = 600.0

# Store-cupboard foods: tagged, but not costed, bought or drawn from the pantry.
_STAPLE_CATEGORIES = frozenset({"Spices and Herbs"})
_STAPLE_PREFIXES = ("Salt, table", "Spices, pepper", "Leavening agents")


class SetupIncomplete(Exception):
    def __init__(self, missing: list[str]) -> None:
        super().__init__("; ".join(missing))
        self.missing = missing


class PlanningError(Exception):
    """A planning outcome the API reports instead of saving: status code + user-facing reasons."""

    def __init__(self, status_code: int, detail: list[str]) -> None:
        super().__init__("; ".join(detail))
        self.status_code = status_code
        self.detail = detail


# --- catalog ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FoodInfo:
    tags: FoodTags
    price: Price
    staple: bool


@dataclass(frozen=True, slots=True)
class PlanningCatalog:
    """Plannable recipes in solver form, priced in GBP (converted per user in make_problem)."""

    catalog: Catalog
    unshoppable: frozenset[int] = frozenset()  # foods never put on a shopping list (tap water)


def is_staple(description: str, category: str | None, p: Price) -> bool:
    return (
        not p.shop
        or (category or "") in _STAPLE_CATEGORIES
        or description.startswith(_STAPLE_PREFIXES)
    )


def food_info(food: db.Food) -> FoodInfo:
    p = price(food.id, food.description, food.category)
    return FoodInfo(
        tag_food(food.id, food.description, food.category),
        p,
        is_staple(food.description, food.category, p),
    )


def solver_food(food: db.Food, info: FoodInfo) -> Food:
    return Food(
        id=food.id,
        name=food.description,
        category=food.category,
        allergens=info.tags.allergens,
        animal=info.tags.animal,
        price_per_kg=info.price.pence_per_kg,
    )


@dataclass(frozen=True, slots=True)
class RecipeFacts:
    """What the planner and the recipe page both derive from a recipe row."""

    slots: frozenset[Slot]
    tags: RecipeTags
    per_portion: Macros | None


def recipe_facts(
    recipe: db.Recipe, foods: Mapping[int, db.Food], info: Mapping[int, FoodInfo]
) -> RecipeFacts:
    """Slots (with data-quality exclusions), tags and per-portion macros of a recipe."""
    total_g = sum(line.grams or 0.0 for line in recipe.ingredients)
    oil_g = sum(
        line.grams or 0.0
        for line in recipe.ingredients
        if line.food_id is not None and foods[line.food_id].category == "Fats and Oils"
    )
    kcal = recipe.kcal if recipe.nutrition_complete else None
    slots = recipe_slots(
        recipe.source, recipe.source_id, recipe.category, kcal, oil_g / total_g if total_g else 0
    )
    lines = [
        make_line(
            line.raw_name,
            line.food_id,
            info[line.food_id].tags if line.food_id is not None else None,
        )
        for line in recipe.ingredients
    ]
    tags = recipe_tags(recipe.name, recipe.category, recipe.instructions, lines)
    per_portion = (
        Macros(
            kcal=round((recipe.kcal or 0) / 2),
            protein_g=round((recipe.protein_g or 0) / 2),
            fat_g=round((recipe.fat_g or 0) / 2),
            carbs_g=round((recipe.carbs_g or 0) / 2),
        )
        if recipe.nutrition_complete
        else None
    )
    return RecipeFacts(slots, tags, per_portion)


def portion_grams(grams: float | None, servings: int, staple: bool) -> int:
    """Whole grams per portion (half a serving), rounded up; staples and sub-gram lines are 0."""
    if grams is None or staple:
        return 0
    exact = grams / servings / 2
    return 0 if exact < 1 else math.ceil(exact)


async def load_catalog(session: AsyncSession) -> PlanningCatalog:
    rows = (
        await session.scalars(
            select(db.Recipe)
            .where(db.Recipe.nutrition_complete, db.Recipe.servings.is_not(None))
            .options(selectinload(db.Recipe.ingredients))
        )
    ).all()
    food_ids = {line.food_id for r in rows for line in r.ingredients if line.food_id is not None}
    foods = {
        f.id: f for f in await session.scalars(select(db.Food).where(db.Food.id.in_(food_ids)))
    }
    info = {fid: food_info(f) for fid, f in foods.items()}
    recipes: dict[int, Recipe] = {}
    for r in rows:
        facts = recipe_facts(r, foods, info)
        if not facts.slots or facts.per_portion is None or r.servings is None:
            continue
        recipes[r.id] = Recipe(
            id=r.id,
            name=r.name,
            meal_types=facts.slots,
            per_portion=facts.per_portion,
            ingredients=tuple(
                Ingredient(
                    line.food_id,
                    portion_grams(line.grams, r.servings, info[line.food_id].staple),
                )
                for line in r.ingredients
                if line.food_id is not None
            ),
            unresolved=facts.tags.unresolved,
            text_allergens=facts.tags.allergens,
            text_animal=facts.tags.animal,
            cuisine=r.cuisine,
        )
    used = {i.food_id for r in recipes.values() for i in r.ingredients}
    return PlanningCatalog(
        catalog=Catalog(
            recipes=recipes,
            foods={fid: solver_food(foods[fid], info[fid]) for fid in used},
        ),
        unshoppable=frozenset(fid for fid in used if not info[fid].price.shop),
    )


class CatalogCache:
    """The plannable catalog, rebuilt at most every CATALOG_TTL_S (one rebuild at a time)."""

    def __init__(self, ttl_s: float = CATALOG_TTL_S) -> None:
        self.ttl_s = ttl_s
        self._value: PlanningCatalog | None = None
        self._loaded = 0.0
        self._lock = asyncio.Lock()

    async def get(self, sessionmaker: async_sessionmaker[AsyncSession]) -> PlanningCatalog:
        if self._value is not None and time.monotonic() - self._loaded < self.ttl_s:
            return self._value
        async with self._lock:
            if self._value is None or time.monotonic() - self._loaded >= self.ttl_s:
                async with sessionmaker() as session:
                    self._value = await load_catalog(session)
                self._loaded = time.monotonic()
            return self._value

    def clear(self) -> None:
        self._value = None


# --- user inputs -> problem -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UserInputs:
    goals: db.Goals
    allergies: db.Allergies
    preferences: db.Preferences
    body: db.BodyProfile | None = None
    pantry: Sequence[db.PantryItem] = ()  # with .food loaded


async def load_inputs(session: AsyncSession, user: db.User) -> UserInputs:
    goals = await session.get(db.Goals, user.id)
    allergies = await session.get(db.Allergies, user.id)
    preferences = await session.get(db.Preferences, user.id)
    missing = [
        message
        for row, message in (
            (goals, "Set your daily calorie goals first."),
            (allergies, "Tell us about allergies (or confirm you have none) first."),
            (preferences, "Tell us about your diet and preferences first."),
        )
        if row is None
    ]
    if goals is None or allergies is None or preferences is None:
        raise SetupIncomplete(missing)
    pantry = (
        await session.scalars(
            select(db.PantryItem)
            .where(db.PantryItem.user_id == user.id)
            .options(selectinload(db.PantryItem.food))
        )
    ).all()
    return UserInputs(
        goals=goals,
        allergies=allergies,
        preferences=preferences,
        body=await session.get(db.BodyProfile, user.id),
        pantry=pantry,
    )


def goal_problems(inputs: UserInputs) -> list[str]:
    """Goals are checked when saved; body stats can change after that (ADR-0008)."""
    g = inputs.goals
    targets = GoalTargets(
        kcal_min=g.kcal_min,
        kcal_max=g.kcal_max,
        calorie_floor=g.calorie_floor,
        max_daily_deficit=g.max_daily_deficit,
        protein_g_min=g.protein_g_min,
        protein_g_max=g.protein_g_max,
        fat_g_min=g.fat_g_min,
        fat_g_max=g.fat_g_max,
        carbs_g_min=g.carbs_g_min,
        carbs_g_max=g.carbs_g_max,
    )
    return validate_targets(targets, tdee(body_from_row(inputs.body)) if inputs.body else None)


def _scaled(value: float | None, factor: float) -> int | None:
    return None if value is None else round(value * factor)


def targets_from(goals: db.Goals, days: int) -> Targets:
    floor = round(goals.calorie_floor)
    daily: dict[Nutrient, Band] = {
        Nutrient.KCAL: Band(max(round(goals.kcal_min), floor), round(goals.kcal_max))
    }
    weekly: dict[Nutrient, Band] = {}
    for nutrient, lo, hi in (
        (Nutrient.PROTEIN, goals.protein_g_min, goals.protein_g_max),
        (Nutrient.FAT, goals.fat_g_min, goals.fat_g_max),
        (Nutrient.CARBS, goals.carbs_g_min, goals.carbs_g_max),
    ):
        if lo is None and hi is None:
            continue
        daily[nutrient] = Band(_scaled(lo, DAILY_MIN_FACTOR), _scaled(hi, DAILY_MAX_FACTOR))
        weekly[nutrient] = Band(_scaled(lo, days), _scaled(hi, days))
    return Targets(daily=daily, weekly=weekly, calorie_floor=floor)


def plan_seed(user_id: int, start: date, version: int) -> int:
    digest = blake2b(f"{user_id}:{start.isoformat()}:{version}".encode(), digest_size=4)
    return int.from_bytes(digest.digest())


def make_problem(
    inputs: UserInputs,
    catalog: PlanningCatalog,
    start: date,
    *,
    days: int = DAYS,
    k: int = 40,
    seed: int = 0,
    novelty: frozenset[int] = frozenset(),
) -> Problem:
    currency: Currency = inputs.goals.currency  # pyright: ignore[reportAssignmentType]
    foods = {
        fid: replace(f, price_per_kg=convert(f.price_per_kg, currency))
        for fid, f in catalog.catalog.foods.items()
    }
    lots: list[Lot] = []
    for item in inputs.pantry:
        expires = (item.expires_on - start).days if item.expires_on else None
        if expires is not None and expires < 0:
            continue
        if item.food_id not in foods:
            info = food_info(item.food)
            f = solver_food(item.food, info)
            foods[item.food_id] = replace(f, price_per_kg=convert(f.price_per_kg, currency))
        lots.append(Lot(item.food_id, math.floor(item.grams), expires))

    targets = targets_from(inputs.goals, days)
    budget = (
        inputs.goals.weekly_budget_minor * days // 7
        if inputs.goals.weekly_budget_minor is not None
        else None
    )
    profile = Profile(
        allergens=frozenset(Allergen(a) for a in inputs.allergies.allergens),
        avoid_food_ids=frozenset(inputs.allergies.avoid_food_ids),
        diet=Diet(inputs.preferences.diet) if inputs.preferences.diet else None,
    )
    prefs = TastePrefs(
        liked_cuisines=frozenset(inputs.preferences.liked_cuisines),
        disliked_cuisines=frozenset(inputs.preferences.disliked_cuisines),
        liked_food_ids=frozenset(inputs.preferences.liked_food_ids),
        disliked_food_ids=frozenset(inputs.preferences.disliked_food_ids),
    )
    specs, recipes = select_candidates(
        Catalog(recipes=catalog.catalog.recipes, foods=foods),
        profile,
        prefs,
        lots,
        [(slot, SLOT_RULES[slot][0]) for slot in SLOT_ORDER],
        targets=targets,
        budget=budget,
        novelty=novelty,
        k=k,
        seed=seed,
    )
    slots = tuple(
        replace(
            s,
            min_portions=SLOT_RULES[s.slot][1],
            max_portions=SLOT_RULES[s.slot][2],
            max_repeats=SLOT_RULES[s.slot][3],
        )
        for s in specs
    )
    problem = Problem(
        start=start,
        days=days,
        slots=slots,
        recipes=recipes,
        foods=foods,
        targets=targets,
        profile=profile,
        pantry=tuple(lots),
        budget=budget,
    )
    if errors := check_problem(problem):
        raise RuntimeError(f"invalid planning problem: {errors}")
    return problem


# --- planner and outcome rules ----------------------------------------------------------------

type Planner = Callable[[Problem], PlanResult]


def run_planner(problem: Problem, mode: str, time_limit_ms: int, workers: int) -> PlanResult:
    """CP-SAT, with the greedy baseline standing in while solve() is unimplemented (auto) or
    when CP-SAT finds no plan in time."""
    if mode == "greedy":
        return greedy(problem, None, time_limit_ms)
    try:
        result = solve(problem, None, time_limit_ms, workers=workers)
    except NotImplementedError:
        if mode == "cpsat":
            raise
        fallback = greedy(problem, None, time_limit_ms)
        return replace(fallback, notes=(*fallback.notes, "Made by the quick planner."))
    if mode == "auto" and result.status == Status.UNKNOWN:
        fallback = greedy(problem, None, time_limit_ms)
        return replace(
            fallback,
            notes=(*fallback.notes, "The optimiser ran out of time; made by the quick planner."),
            wall_ms=fallback.wall_ms + result.wall_ms,
        )
    return result


_NO_PLAN = (
    "We couldn't fit a week of meals to your goals and restrictions. Try a wider calorie range, "
    "a bigger budget or fewer avoided foods."
)


def check_outcome(problem: Problem, result: PlanResult) -> tuple[Plan, list[Violation]]:
    """Apply the outcome rules; returns the plan to save and its (allowed) violations."""
    if result.plan is None:
        if result.status == Status.UNKNOWN:
            raise PlanningError(503, ["Planning took too long. Please try again."])
        if result.status == Status.INVALID:
            logger.error("planner %s returned INVALID", result.planner)
            raise PlanningError(500, ["Something went wrong building your plan."])
        raise PlanningError(400, diagnose(problem) or [_NO_PLAN])
    violations = validate(problem, result.plan)
    blocking = [v for v in violations if v.code in SAFETY_CODES | STRUCTURAL_CODES]
    if blocking and all(v.code == Code.CALORIE_FLOOR for v in blocking):
        raise PlanningError(400, [v.message for v in blocking] + diagnose(problem))
    if blocking or (result.planner == "cpsat" and hard(violations)):
        offending = blocking or hard(violations)
        logger.error(
            "planner %s produced an invalid plan: %s",
            result.planner,
            sorted({v.code.value for v in offending}),
        )
        raise PlanningError(500, ["Something went wrong building your plan; nothing was saved."])
    return result.plan, violations


# --- persistence and read model ---------------------------------------------------------------


class PlanStats(BaseModel):
    """Snapshot stored with a plan (meal_plans.stats): PlanOut never reads live goals or prices."""

    v: int = 1
    targets: TargetsOut
    budget_minor: int | None
    cost_millipence: int
    cost_minor: int
    pantry_used_g: int
    waste_g: int
    waste_millipence: int
    score: dict[str, int]
    violations: list[ViolationOut]
    notes: list[str]
    candidates: dict[str, int]
    seed: int
    time_limit_ms: int
    planner_ms: int
    total_ms: int = 0
    excluded_allergens: list[Allergen]
    diet: Diet | None
    day_totals: list[MacrosOut]


def macros_out(m: Macros) -> MacrosOut:
    return MacrosOut(kcal=m.kcal, protein_g=m.protein_g, fat_g=m.fat_g, carbs_g=m.carbs_g)


def _band_out(band: Band | None) -> BandOut | None:
    return None if band is None else BandOut(min=band.min, max=band.max)


def _bands(bands: Mapping[Nutrient, Band]) -> NutrientBands:
    return NutrientBands(**{n.value: _band_out(bands.get(n)) for n in Nutrient})


def violation_out(v: Violation) -> ViolationOut:
    return ViolationOut(
        code=v.code.value,
        message=v.message,
        hard=v.hard,
        day=v.day,
        slot=v.slot,
        recipe_id=v.recipe_id,
    )


def plan_stats(
    problem: Problem,
    result: PlanResult,
    plan: Plan,
    violations: Iterable[Violation],
    *,
    seed: int,
    time_limit_ms: int,
) -> PlanStats:
    alloc = allocate(problem, plan)
    s = score(problem, plan)
    cost = cost_millipence(problem, alloc.buy)
    return PlanStats(
        targets=TargetsOut(
            daily=_bands(problem.targets.daily),
            weekly=_bands(problem.targets.weekly),
            calorie_floor=problem.targets.calorie_floor,
        ),
        budget_minor=problem.budget,
        cost_millipence=cost,
        cost_minor=to_minor(cost),
        pantry_used_g=sum(alloc.pantry_used.values()),
        waste_g=sum(alloc.waste.values()),
        waste_millipence=waste_millipence(problem, alloc.waste),
        score={**s.terms, "total": s.total},
        violations=[violation_out(v) for v in violations],
        notes=list(result.notes),
        candidates={spec.slot.value: len(spec.candidates) for spec in problem.slots},
        seed=seed,
        time_limit_ms=time_limit_ms,
        planner_ms=result.wall_ms,
        excluded_allergens=sorted(problem.profile.allergens),
        diet=problem.profile.diet,
        day_totals=[macros_out(m) for m in day_totals(problem, plan)],
    )


@dataclass(slots=True)
class Prepared:
    problem: Problem
    version: int
    seed: int
    parent_id: int | None
    novelty: frozenset[int] = field(default_factory=frozenset[int])


async def latest_plan(session: AsyncSession, user_id: int) -> db.MealPlan | None:
    return await session.scalar(
        select(db.MealPlan)
        .where(db.MealPlan.user_id == user_id)
        .order_by(db.MealPlan.created_at.desc(), db.MealPlan.id.desc())
        .limit(1)
        .options(selectinload(db.MealPlan.meals))
    )


async def next_version(session: AsyncSession, user_id: int, start: date) -> int:
    current = await session.scalar(
        select(func.max(db.MealPlan.version)).where(
            db.MealPlan.user_id == user_id, db.MealPlan.start_date == start
        )
    )
    return (current or 0) + 1


def save_plan(
    session: AsyncSession,
    user_id: int,
    prepared: Prepared,
    result: PlanResult,
    plan: Plan,
    stats: PlanStats,
    currency: str,
    unshoppable: frozenset[int],
) -> db.MealPlan:
    problem = prepared.problem
    row = db.MealPlan(
        user_id=user_id,
        start_date=problem.start,
        days=problem.days,
        version=prepared.version,
        parent_id=prepared.parent_id,
        planner=result.planner,
        status=result.status.value,
        objective=result.objective,
        solve_ms=result.wall_ms,
        currency=currency,
        stats=stats.model_dump(mode="json"),
    )
    for meal in sorted(plan.meals, key=lambda m: (m.day, SLOT_ORDER.index(m.slot))):
        m = problem.recipes[meal.recipe_id].per_portion.times(meal.portions)
        row.meals.append(
            db.PlanMeal(
                day=meal.day,
                slot=meal.slot.value,
                recipe_id=meal.recipe_id,
                portions=meal.portions,
                kcal=m.kcal,
                protein_g=m.protein_g,
                fat_g=m.fat_g,
                carbs_g=m.carbs_g,
                status="planned",
                locked=False,
            )
        )
    for line in shopping_list(problem, plan).lines:
        if line.food_id in unshoppable:
            continue
        row.shopping.append(
            db.ShoppingItem(
                food_id=line.food_id,
                grams=line.grams,
                cost_minor=line.cost_minor,
                staple=line.staple,
                checked=False,
            )
        )
    session.add(row)
    return row


def plan_dates(start: date, days: int) -> list[date]:
    return [start + timedelta(days=d) for d in range(days)]
