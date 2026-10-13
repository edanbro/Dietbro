"""Planning service: database -> solver Problem -> planner -> independent validator -> saved plan.

The rules live in pure packages (larder_solver, larder_core); this module only gathers inputs,
converts units at the boundary and applies the outcome rules of docs/adr/0009-planning-contract.md:
a plan with a safety or structural violation is never saved, whatever planner made it.

Replans from the chat (docs/adr/0014-chat-replans.md) use the same pieces: `make_problem` over
the open horizon with the reported facts and wishes applied (`constrain`), the planner with the
parent plan as `previous`, and `save_plan` with the parent's past rows carried over.
"""

import asyncio
import logging
import math
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from hashlib import blake2b
from typing import Literal

import anyio
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from larder_api.routers.profile import body_from_row
from larder_api.schemas import (
    BandOut,
    MacrosOut,
    MealLogOut,
    MealOut,
    NutrientBands,
    RecipeCard,
    TargetsOut,
    ViolationOut,
)
from larder_api.settings import Settings
from larder_core.allergens import Allergen
from larder_core.energy import Targets as GoalTargets
from larder_core.energy import tdee, validate_targets
from larder_core.meals import SLOT_ORDER, Slot, recipe_slots
from larder_core.prices import PER_GBP, Currency, Price, price
from larder_core.regions import local_price
from larder_core.tagging import (
    FORBIDDEN,
    Diet,
    FoodTags,
    RecipeTags,
    make_line,
    recipe_tags,
    tag_food,
)
from larder_db import models as db
from larder_llm.outcome import ReplanOutcome
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
    Meal,
    Nutrient,
    Plan,
    PlanResult,
    Problem,
    Profile,
    Recipe,
    Status,
    Targets,
    Violation,
    Weights,
    check_problem,
    diagnose,
    greedy,
    hard,
    score,
    shopping_list,
    solve,
    validate,
)
from larder_solver.candidates import TastePrefs, preference
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
class RecipeText:
    """What recipe search matches words against (the planner doesn't need it)."""

    category: str | None
    tags: tuple[str, ...]  # TheMealDB tags
    ingredients: tuple[str, ...]  # ingredient lines as written


@dataclass(frozen=True, slots=True)
class PlanningCatalog:
    """Plannable recipes in solver form, priced in GBP (converted per user in make_problem).
    The shared one (owner IS NULL) is cached per process; a user's private recipes are loaded
    per request (`load_private_recipes`) and merged, never cached."""

    catalog: Catalog
    unshoppable: frozenset[int] = frozenset()  # foods never put on a shopping list (tap water)
    text: Mapping[int, RecipeText] = field(default_factory=dict[int, RecipeText])

    def merged(self, other: "PlanningCatalog | None") -> "PlanningCatalog":
        if other is None or not other.catalog.recipes:
            return self
        return PlanningCatalog(
            Catalog(
                recipes={**self.catalog.recipes, **other.catalog.recipes},
                foods={**self.catalog.foods, **other.catalog.foods},
            ),
            self.unshoppable | other.unshoppable,
            {**self.text, **other.text},
        )


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


def solver_recipe(
    recipe: db.Recipe, facts: RecipeFacts, info: Mapping[int, FoodInfo]
) -> Recipe | None:
    """The recipe in solver form, or None when it can't be planned (no slot, incomplete
    nutrition, no serving count)."""
    if not facts.slots or facts.per_portion is None or recipe.servings is None:
        return None
    return Recipe(
        id=recipe.id,
        name=recipe.name,
        meal_types=facts.slots,
        per_portion=facts.per_portion,
        ingredients=tuple(
            Ingredient(
                line.food_id,
                portion_grams(line.grams, recipe.servings, info[line.food_id].staple),
            )
            for line in recipe.ingredients
            if line.food_id is not None
        ),
        unresolved=facts.tags.unresolved,
        text_allergens=facts.tags.allergens,
        text_animal=facts.tags.animal,
        cuisine=recipe.cuisine,
    )


def unsafe_reasons(recipe: Recipe, foods: Mapping[int, Food], profile: Profile) -> list[str]:
    """Why `candidates.allowed` rejects the recipe for this profile, in words ([] = allowed)."""
    allergens = set(recipe.text_allergens)
    animal = set(recipe.text_animal)
    avoided: list[str] = []
    unknown = False
    for i in recipe.ingredients:
        f = foods.get(i.food_id)
        if f is None:
            unknown = True
            continue
        allergens |= f.allergens
        animal |= f.animal
        if i.food_id in profile.avoid_food_ids and f.name not in avoided:
            avoided.append(f.name)
    reasons: list[str] = []
    if hit := allergens & profile.allergens:
        reasons.append("contains " + ", ".join(sorted(a.replace("_", " ") for a in hit)))
    if avoided:
        reasons.append(f"contains {', '.join(avoided)}, which you avoid")
    if profile.diet is not None and animal & FORBIDDEN[profile.diet]:
        reasons.append(f"isn't {profile.diet}")
    if unknown:
        reasons.append("uses an ingredient we have no data for")
    if recipe.unresolved > 0 and profile.restricted:
        reasons.append("has ingredients we couldn't check against your allergies and diet")
    return reasons


async def load_foods(
    session: AsyncSession, food_ids: Iterable[int]
) -> tuple[dict[int, db.Food], dict[int, FoodInfo]]:
    foods = {
        f.id: f for f in await session.scalars(select(db.Food).where(db.Food.id.in_(set(food_ids))))
    }
    return foods, {fid: food_info(f) for fid, f in foods.items()}


async def _load(session: AsyncSession, owner: ColumnElement[bool]) -> PlanningCatalog:
    rows = (
        await session.scalars(
            select(db.Recipe)
            .where(db.Recipe.nutrition_complete, db.Recipe.servings.is_not(None), owner)
            .options(selectinload(db.Recipe.ingredients), selectinload(db.Recipe.tags))
        )
    ).all()
    foods, info = await load_foods(
        session, (line.food_id for r in rows for line in r.ingredients if line.food_id is not None)
    )
    recipes: dict[int, Recipe] = {}
    text: dict[int, RecipeText] = {}
    for r in rows:
        recipe = solver_recipe(r, recipe_facts(r, foods, info), info)
        if recipe is None:
            continue
        recipes[r.id] = recipe
        text[r.id] = RecipeText(
            r.category,
            tuple(sorted(t.tag for t in r.tags)),
            tuple(line.raw_name for line in r.ingredients),
        )
    used = {i.food_id for r in recipes.values() for i in r.ingredients}
    return PlanningCatalog(
        catalog=Catalog(
            recipes=recipes,
            foods={fid: solver_food(foods[fid], info[fid]) for fid in used},
        ),
        unshoppable=frozenset(fid for fid in used if not info[fid].price.shop),
        text=text,
    )


async def load_catalog(session: AsyncSession) -> PlanningCatalog:
    """The shared catalogue: every plannable recipe with no owner."""
    return await _load(session, db.Recipe.owner_user_id.is_(None))


async def load_private_recipes(session: AsyncSession, user_id: int) -> PlanningCatalog:
    """The user's own (generated) plannable recipes; loaded per request, never cached."""
    return await _load(session, db.Recipe.owner_user_id == user_id)


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
    country: str | None = None  # prices are estimated for this region (larder_core.regions)


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
        country=user.country,
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


def profile_of(allergies: db.Allergies, preferences: db.Preferences) -> Profile:
    """The hard exclusions, as the planner and every chat tool apply them."""
    return Profile(
        allergens=frozenset(Allergen(a) for a in allergies.allergens),
        avoid_food_ids=frozenset(allergies.avoid_food_ids),
        diet=Diet(preferences.diet) if preferences.diet else None,
    )


def taste_of(preferences: db.Preferences) -> TastePrefs:
    return TastePrefs(
        liked_cuisines=frozenset(preferences.liked_cuisines),
        disliked_cuisines=frozenset(preferences.disliked_cuisines),
        liked_food_ids=frozenset(preferences.liked_food_ids),
        disliked_food_ids=frozenset(preferences.disliked_food_ids),
    )


def pantry_key(item: db.PantryItem, known: Mapping[int, object]) -> int:
    """The food a pantry item counts as: its generic food when that is in `known` (the
    planning catalogue), else itself. `item.food` must be loaded."""
    generic = item.food.generic_food_id
    return generic if generic is not None and generic in known else item.food_id


def _priced(f: Food, currency: Currency, country: str | None) -> Food:
    """A catalogue food (GBP pence/kg, UK estimate) priced for the user's region and currency."""
    return replace(f, price_per_kg=local_price(f.price_per_kg, f.category, country, currency))


def weights_for(currency: Currency) -> Weights:
    """The objective weights with their money terms in `currency` minor units, so a repeat or a
    snack is worth about the same to a user whatever they pay in (GBP: the defaults)."""
    w, rate = Weights(), PER_GBP[currency]
    money = ("preference", "pantry", "repeat", "optional_meal", "macro", "churn")
    return replace(w, **{name: round(getattr(w, name) * rate) for name in money})


type Cell = tuple[int, Slot]


def make_problem(
    inputs: UserInputs,
    catalog: PlanningCatalog,
    start: date,
    *,
    days: int = DAYS,
    k: int = 40,
    seed: int = 0,
    novelty: frozenset[int] = frozenset(),
    private: PlanningCatalog | None = None,
    choices: Mapping[Cell, tuple[int, ...]] | None = None,
    empty: Iterable[Cell] = (),
    extra: Mapping[int, Macros] | None = None,
) -> Problem:
    """The problem for `days` days from `start`: the prefilter over the shared catalogue merged
    with the user's `private` recipes, then (replans) `constrain` with the fixed state."""
    pool = catalog.merged(private)
    currency: Currency = inputs.goals.currency  # pyright: ignore[reportAssignmentType]
    foods = {fid: _priced(f, currency, inputs.country) for fid, f in pool.catalog.foods.items()}
    lots: list[Lot] = []
    for item in inputs.pantry:
        expires = (item.expires_on - start).days if item.expires_on else None
        if expires is not None and expires < 0:
            continue
        # A product or regional food counts as its generic when recipes use the generic.
        fid = pantry_key(item, foods)
        if fid not in foods:
            basis = solver_food(item.food, food_info(item.food))
            foods[fid] = _priced(basis, currency, inputs.country)
        lots.append(Lot(fid, math.floor(item.grams), expires))

    targets = targets_from(inputs.goals, days)
    budget = (
        inputs.goals.weekly_budget_minor * days // 7
        if inputs.goals.weekly_budget_minor is not None
        else None
    )
    profile = profile_of(inputs.allergies, inputs.preferences)
    specs, recipes = select_candidates(
        Catalog(recipes=pool.catalog.recipes, foods=foods),
        profile,
        taste_of(inputs.preferences),
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
        weights=weights_for(currency),
    )
    return constrain(problem, inputs, pool, choices=choices or {}, empty=empty, extra=extra or {})


def constrain(
    problem: Problem,
    inputs: UserInputs,
    pool: PlanningCatalog,
    *,
    choices: Mapping[Cell, tuple[int, ...]],
    empty: Iterable[Cell] = (),
    extra: Mapping[int, Macros],
) -> Problem:
    """A replan's fixed state on top of a prefiltered problem (ADR-0014): the recipes named in
    `choices` (from `pool`, with their foods priced in the user's currency and their preference
    set), cells kept `empty` (locked to None), intake already fixed per day (`extra`), and the
    per-day kcal bands that follow (`day_bands`). Raises if the result breaks check_problem."""
    currency: Currency = inputs.goals.currency  # pyright: ignore[reportAssignmentType]
    prefs = taste_of(inputs.preferences)
    recipes = dict(problem.recipes)
    foods = dict(problem.foods)
    for rid in {r for ids in choices.values() for r in ids} - recipes.keys():
        recipe = pool.catalog.recipes.get(rid)
        if recipe is None:
            continue  # check_problem reports it
        recipes[rid] = replace(recipe, preference=preference(recipe, prefs))
        for i in recipe.ingredients:
            if i.food_id not in foods and i.food_id in pool.catalog.foods:
                foods[i.food_id] = _priced(pool.catalog.foods[i.food_id], currency, inputs.country)
    out = replace(
        problem,
        recipes=recipes,
        foods=foods,
        choices=dict(choices),
        locked=dict.fromkeys(empty),
        extra={d: m for d, m in extra.items() if m != Macros()},
    )
    out = replace(out, day_kcal=day_bands(out))
    if errors := check_problem(out):
        raise RuntimeError(f"invalid planning problem: {errors}")
    return out


async def active_logs(
    session: AsyncSession, user_id: int, start: date, days: int
) -> list[db.MealLog]:
    """The user's meal logs (not voided) dated in [start, start + days)."""
    return list(
        await session.scalars(
            select(db.MealLog)
            .where(
                db.MealLog.user_id == user_id,
                db.MealLog.voided_at.is_(None),
                db.MealLog.eaten_on >= start,
                db.MealLog.eaten_on < start + timedelta(days=days),
            )
            .order_by(db.MealLog.id)
        )
    )


def with_logs(
    problem: Problem, inputs: UserInputs, pool: PlanningCatalog, logs: Iterable[db.MealLog]
) -> Problem:
    """A new plan around food already logged in its dates: a logged meal's slot stays empty
    and every log's macros count on its day (`constrain`, so its day band follows)."""
    extra: dict[int, Macros] = {}
    empty: set[Cell] = set()
    for log in logs:
        d = (log.eaten_on - problem.start).days
        extra[d] = extra.get(d, Macros()) + Macros(log.kcal, log.protein_g, log.fat_g, log.carbs_g)
        if log.slot is not None:
            empty.add((d, Slot(log.slot)))
    if not extra and not empty:
        return problem
    return constrain(problem, inputs, pool, choices={}, empty=empty, extra=extra)


def log_kind(log: db.MealLog) -> Literal["off_plan", "skipped", "eaten"]:
    return "eaten" if log.kind == "eaten" else "off_plan" if log.kind == "off_plan" else "skipped"


def logged_out(log: db.MealLog) -> MealLogOut:
    return MealLogOut(
        date=log.eaten_on,
        slot=Slot(log.slot) if log.slot else None,
        kind=log_kind(log),
        description=log.description,
        kcal=log.kcal,
        estimated=log.estimated,
        recipe_id=log.recipe_id,
    )


def logged_by_day(logs: Iterable[db.MealLog], start: date, days: int) -> list[list[MealLogOut]]:
    """PlanStats.logged: each plan day's logs."""
    out: list[list[MealLogOut]] = [[] for _ in range(days)]
    for log in logs:
        if 0 <= (d := (log.eaten_on - start).days) < days:
            out[d].append(logged_out(log))
    return out


def day_reach(problem: Problem, day: int) -> tuple[int, int]:
    """The least and most kcal the day's open cells can add: each chosen or required cell
    between its slot's lightest candidate at the fewest portions and its heaviest at the most;
    optional slots from nothing up to their heaviest. Over the slot's candidates, not a cell's
    choices: a wish (or pin) must fit the day's band, never set it (two broth cravings would
    otherwise take the day under the floor)."""
    least = most = 0
    for spec in problem.slots:
        cell = (day, spec.slot)
        if cell in problem.locked:
            meal = problem.locked[cell]
            if meal is not None and meal.recipe_id in problem.recipes:
                kcal = problem.recipes[meal.recipe_id].per_portion.kcal * meal.portions
                least, most = least + kcal, most + kcal
            continue
        ids = spec.candidates or problem.choices.get(cell, ())
        kcal = [problem.recipes[r].per_portion.kcal for r in ids if r in problem.recipes]
        if not kcal:
            continue
        lo, hi = problem.portion_range(spec.slot)
        if spec.required or cell in problem.choices:
            least += min(kcal) * lo
        most += max(kcal) * hi
    return least, most


def day_bands(problem: Problem) -> dict[int, Band]:
    """The per-day kcal band for every day whose intake is partly fixed (off-plan food, a meal
    already eaten, or a slot kept empty): the user's band, clipped to what the open cells can
    still reach - Band(min(usual min, fixed + most), max(usual max, fixed + least)). Its min is
    always set (an open min would mean no lower bound at all)."""
    band = problem.targets.daily.get(Nutrient.KCAL, Band())
    usual_min = max(problem.targets.calorie_floor, band.min or 0)
    fixed_days = {d for d, m in problem.extra.items() if m.kcal > 0} | {
        d for (d, _), meal in problem.locked.items() if meal is None
    }
    out: dict[int, Band] = {}
    for day in sorted(fixed_days):
        fixed = problem.extra.get(day, Macros()).kcal
        least, most = day_reach(problem, day)
        high = None if band.max is None else max(band.max, fixed + least)
        out[day] = Band(min(usual_min, fixed + most), high)
    return out


# --- planner and outcome rules ----------------------------------------------------------------

# A planner sees the problem and the plan it replaces (None for a new plan): the churn weight
# keeps unchanged meals where they were (ADR-0014).
type Planner = Callable[[Problem, Plan | None], PlanResult]


def run_planner(
    problem: Problem, previous: Plan | None, mode: str, time_limit_ms: int, workers: int
) -> PlanResult:
    """CP-SAT, with the greedy baseline standing in while solve() is unimplemented (auto) or
    when CP-SAT finds no plan in time."""
    if mode == "greedy":
        return greedy(problem, previous, time_limit_ms)
    try:
        result = solve(problem, previous, time_limit_ms, workers=workers)
    except NotImplementedError:
        if mode == "cpsat":
            raise
        fallback = greedy(problem, previous, time_limit_ms)
        return replace(fallback, notes=(*fallback.notes, "Made by the quick planner."))
    if mode == "auto" and result.status == Status.UNKNOWN:
        fallback = greedy(problem, previous, time_limit_ms)
        return replace(
            fallback,
            notes=(*fallback.notes, "The optimiser ran out of time; made by the quick planner."),
            wall_ms=fallback.wall_ms + result.wall_ms,
        )
    return result


_limiter: anyio.CapacityLimiter | None = None


def plan_limiter(settings: Settings) -> anyio.CapacityLimiter:
    """Process-wide cap on concurrent solves (each uses several CPU threads), shared by
    POST /plans and chat replans."""
    global _limiter
    if _limiter is None:
        _limiter = anyio.CapacityLimiter(settings.plan_concurrency)
    return _limiter


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
    """Snapshot stored with a plan (meal_plans.stats): PlanOut never reads live goals or prices.

    v2 (chat replans) adds `logged` and `outcome`; v1 rows load with both empty."""

    v: int = 2
    targets: TargetsOut
    budget_minor: int | None
    cost_millipence: int
    cost_minor: int
    pantry_used_g: int
    waste_g: int
    waste_millipence: int
    score: dict[str, int]  # objective terms; 'churn' counts slots changed vs the parent (x weight)
    violations: list[ViolationOut]
    notes: list[str]
    candidates: dict[str, int]
    seed: int
    time_limit_ms: int
    planner_ms: int
    total_ms: int = 0
    excluded_allergens: list[Allergen]
    diet: Diet | None
    day_totals: list[MacrosOut]  # per day: its meals + its logged food
    # Per day: food logged off-plan and skipped meals (active meal_logs when this was saved).
    logged: list[list[MealLogOut]] = Field(default_factory=list[list[MealLogOut]])
    # What the chat change that made this version did (results + diff), for explain_plan_diff.
    outcome: ReplanOutcome | None = None

    def logged_on(self, day: int) -> list[MealLogOut]:
        return self.logged[day] if day < len(self.logged) else []


def macros_out(m: Macros) -> MacrosOut:
    return MacrosOut(kcal=m.kcal, protein_g=m.protein_g, fat_g=m.fat_g, carbs_g=m.carbs_g)


def _band_out(band: Band | None) -> BandOut | None:
    return None if band is None else BandOut(min=band.min, max=band.max)


def _bands(bands: Mapping[Nutrient, Band]) -> NutrientBands:
    return NutrientBands(**{n.value: _band_out(bands.get(n)) for n in Nutrient})


def targets_out(targets: Targets) -> TargetsOut:
    return TargetsOut(
        daily=_bands(targets.daily),
        weekly=_bands(targets.weekly),
        calorie_floor=targets.calorie_floor,
    )


def violation_out(v: Violation, offset: int = 0) -> ViolationOut:
    return ViolationOut(
        code=v.code.value,
        message=v.message,
        hard=v.hard,
        day=None if v.day is None else v.day + offset,
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
    previous: Plan | None = None,
) -> PlanStats:
    alloc = allocate(problem, plan)
    s = score(problem, plan, previous)
    cost = cost_millipence(problem, alloc.buy)
    return PlanStats(
        targets=targets_out(problem.targets),
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


@dataclass(frozen=True, slots=True)
class Carried:
    """What a replan's version keeps from its parent: the plan's own dates (the problem covers
    only days `offset`.. of them), rows copied verbatim (past days, meals already eaten today),
    the cells (problem days) saved as pinned, and the parent's shopping list, whose ticks carry
    over for a food still needed in no larger amount."""

    start: date
    days: int
    offset: int
    meals: Sequence[db.PlanMeal] = ()
    pinned: frozenset[Cell] = frozenset()
    shopping: Sequence[db.ShoppingItem] = ()


async def latest_plan(session: AsyncSession, user_id: int) -> db.MealPlan | None:
    return await session.scalar(
        select(db.MealPlan)
        .where(db.MealPlan.user_id == user_id)
        .order_by(db.MealPlan.created_at.desc(), db.MealPlan.id.desc())
        .limit(1)
        .options(selectinload(db.MealPlan.meals), selectinload(db.MealPlan.shopping))
    )


async def lock_user_plans(session: AsyncSession, user_id: int) -> None:
    """Serialise plan saves per user until the transaction ends (POST /plans, chat replans)."""
    await session.execute(select(func.pg_advisory_xact_lock(user_id)))


async def next_version(session: AsyncSession, user_id: int, start: date) -> int:
    current = await session.scalar(
        select(func.max(db.MealPlan.version)).where(
            db.MealPlan.user_id == user_id, db.MealPlan.start_date == start
        )
    )
    return (current or 0) + 1


def copy_meal(meal: db.PlanMeal) -> db.PlanMeal:
    return db.PlanMeal(
        day=meal.day,
        slot=meal.slot,
        recipe_id=meal.recipe_id,
        portions=meal.portions,
        kcal=meal.kcal,
        protein_g=meal.protein_g,
        fat_g=meal.fat_g,
        carbs_g=meal.carbs_g,
        status=meal.status,
        locked=meal.locked,
    )


def save_plan(
    session: AsyncSession,
    user_id: int,
    prepared: Prepared,
    result: PlanResult,
    plan: Plan,
    stats: PlanStats,
    currency: str,
    unshoppable: frozenset[int],
    carried: Carried | None = None,
) -> db.MealPlan:
    problem = prepared.problem
    offset = carried.offset if carried else 0
    row = db.MealPlan(
        user_id=user_id,
        start_date=carried.start if carried else problem.start,
        days=carried.days if carried else problem.days,
        version=prepared.version,
        parent_id=prepared.parent_id,
        planner=result.planner,
        status=result.status.value,
        objective=result.objective,
        solve_ms=result.wall_ms,
        currency=currency,
        stats=stats.model_dump(mode="json"),
    )
    pinned = carried.pinned if carried else frozenset[Cell]()
    meals = [copy_meal(m) for m in carried.meals] if carried else []
    for meal in plan.meals:
        m = problem.recipes[meal.recipe_id].per_portion.times(meal.portions)
        meals.append(
            db.PlanMeal(
                day=meal.day + offset,
                slot=meal.slot.value,
                recipe_id=meal.recipe_id,
                portions=meal.portions,
                kcal=m.kcal,
                protein_g=m.protein_g,
                fat_g=m.fat_g,
                carbs_g=m.carbs_g,
                status="planned",
                locked=(meal.day, meal.slot) in pinned,
            )
        )
    row.meals.extend(sorted(meals, key=lambda m: (m.day, SLOT_ORDER.index(Slot(m.slot)))))
    before = {s.food_id: s for s in carried.shopping} if carried else {}
    for line in shopping_list(problem, plan).lines:
        if line.food_id in unshoppable:
            continue
        old = before.get(line.food_id)
        row.shopping.append(
            db.ShoppingItem(
                food_id=line.food_id,
                grams=line.grams,
                cost_minor=line.cost_minor,
                staple=line.staple,
                checked=old is not None and old.checked and line.grams <= old.grams,
            )
        )
    session.add(row)
    return row


def meal_out(m: db.PlanMeal) -> MealOut:
    """A saved meal for the client (its `recipe` must be loaded)."""
    r = m.recipe
    return MealOut(
        slot=Slot(m.slot),
        recipe=RecipeCard(
            id=r.id, name=r.name, category=r.category, cuisine=r.cuisine, image_url=r.image_url
        ),
        portions=m.portions,
        servings=m.portions / 2,
        nutrition=MacrosOut(kcal=m.kcal, protein_g=m.protein_g, fat_g=m.fat_g, carbs_g=m.carbs_g),
        locked=m.locked,
        status="eaten" if m.status == "eaten" else "planned",
    )


def plan_dates(start: date, days: int) -> list[date]:
    return [start + timedelta(days=d) for d in range(days)]


def meals_plan(meals: Iterable[db.PlanMeal], offset: int = 0) -> Plan:
    """Saved rows as a solver Plan, days shifted by -offset (rows before it are left out)."""
    return Plan(
        tuple(
            Meal(m.day - offset, Slot(m.slot), m.recipe_id, m.portions)
            for m in meals
            if m.day >= offset
        )
    )
