"""Seeded planning problems for tests, evals and the bench. Pure: every random choice comes from
`random.Random(seed)` and never from set or hash order, so a seed means the same problem in any
process.

- `synthetic_catalog`: a plausible recipe and food catalogue; no database needed.
- `planted`: a problem built around a known valid plan (the witness), plus decoy recipes that
  each break one hard filter, so any planner can be checked by the validator.
- `infeasible`: a planted problem whose daily kcal band no plan can reach.
- `realistic`: a user-like profile and targets over a given catalogue, for the bench; no
  feasibility guarantee.
"""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from enum import StrEnum
from random import Random

from larder_core.tagging import FoodTags
from larder_solver.candidates import TastePrefs, allowed, select
from larder_solver.metrics import allocate, cost_millipence, day_totals, to_minor, usage
from larder_solver.problem import (
    SLOT_ORDER,
    Allergen,
    AnimalTag,
    Band,
    Catalog,
    Diet,
    Food,
    Ingredient,
    Lot,
    Macros,
    Meal,
    Nutrient,
    Plan,
    Problem,
    Profile,
    Recipe,
    Slot,
    SlotSpec,
    Targets,
    check_problem,
)
from larder_solver.validate import hard, validate

FLOOR = 1200  # kcal; planted and realistic problems use the default calorie floor
START = date(2026, 1, 5)  # a Monday; scenarios start on one of the following seven days

# slot -> (required, min portions, max portions, max repeats): the M3 slot defaults.
SLOT_LIMITS: dict[Slot, tuple[bool, int, int, int | None]] = {
    Slot.BREAKFAST: (True, 1, 3, 4),
    Slot.LUNCH: (True, 1, 4, None),
    Slot.DINNER: (True, 2, 4, None),
    Slot.SNACK: (False, 1, 2, 4),
}


class DecoyPath(StrEnum):
    """How a decoy recipe breaks the profile, one hard-filter path each."""

    FOOD_ALLERGEN = "food_allergen"  # an ingredient food carries an excluded allergen
    TEXT_ALLERGEN = "text_allergen"  # only the recipe text does
    TEXT_ANIMAL = "text_animal"  # only the text names an animal product the diet forbids
    AVOIDED = "avoided"  # an ingredient is an avoided food
    UNRESOLVED = "unresolved"  # an ingredient line couldn't be checked
    UNKNOWN_FOOD = "unknown_food"  # an ingredient food is missing from the problem


@dataclass(frozen=True, slots=True)
class Scenario:
    problem: Problem
    witness: Plan | None  # a plan with no hard violations, when one is known
    # Decoy recipe id -> the hard filter it breaks; a correct planner never picks one.
    decoys: Mapping[int, DecoyPath] = field(default_factory=dict[int, DecoyPath])


# --- synthetic catalogue -------------------------------------------------------------------------

_CUISINES: tuple[str | None, ...] = (
    "British",
    "Italian",
    "Indian",
    "Mexican",
    "Chinese",
    "Thai",
    "French",
    "Greek",
    "Japanese",
    None,
)
_CATEGORIES = (
    "Vegetables and Vegetable Products",
    "Fruits and Fruit Juices",
    "Legumes and Legume Products",
    "Cereal Grains and Pasta",
    "Dairy and Egg Products",
    "Poultry Products",
    "Finfish and Shellfish Products",
    "Nut and Seed Products",
    "Fats and Oils",
    "Baked Products",
)
# (meal types, name, kcal per portion range, share of recipes)
_KINDS: tuple[tuple[frozenset[Slot], str, int, int, float], ...] = (
    (frozenset({Slot.BREAKFAST}), "breakfast", 150, 250, 0.2),
    (frozenset({Slot.LUNCH, Slot.DINNER}), "main", 250, 380, 0.45),
    (frozenset({Slot.LUNCH}), "starter", 120, 220, 0.1),
    (frozenset({Slot.SNACK}), "snack", 80, 200, 0.2),
    (frozenset({Slot.BREAKFAST, Slot.SNACK}), "pot", 150, 200, 0.05),
)
_TAGS: tuple[FoodTags, ...] = (
    *(FoodTags(frozenset({a})) for a in Allergen),
    FoodTags(animal=frozenset({AnimalTag.MEAT})),
    FoodTags(animal=frozenset({AnimalTag.MEAT})),
    FoodTags(animal=frozenset({AnimalTag.MEAT})),
    FoodTags(animal=frozenset({AnimalTag.SHELLFISH})),
    FoodTags(animal=frozenset({AnimalTag.HONEY})),
    FoodTags(animal=frozenset({AnimalTag.GELATIN})),
    FoodTags(frozenset({Allergen.MILK}), frozenset({AnimalTag.RENNET})),
)


def _tags(rng: Random) -> FoodTags:
    tags = FoodTags()
    for t in rng.sample(_TAGS, rng.choice((1, 1, 2))):
        tags |= t
    return tags.normalised()


def synthetic_catalog(seed: int, n_recipes: int = 300, n_foods: int = 150) -> Catalog:
    """Foods 1..n_foods (the first ~8% are 0 g staples, price 0; ~15% carry tags) and recipes
    1..n_recipes: breakfasts 150-250 kcal per portion, mains 250-380, starters 120-220, snacks
    80-200, with kcal within ~10% of 4p + 9f + 4c, 3-10 ingredients, a few unresolved lines and
    text-only tags. Prices 50-3000 per kg, log-uniform."""
    rng = Random(seed)
    n_staples = max(1, n_foods // 12)
    foods: dict[int, Food] = {}
    for fid in range(1, n_foods + 1):
        tags = _tags(rng) if rng.random() < 0.15 else FoodTags()
        if fid <= n_staples:
            foods[fid] = Food(fid, f"Spice {fid}", "Spices and Herbs", tags.allergens, tags.animal)
            continue
        category = rng.choice(_CATEGORIES)
        price = round(math.exp(rng.uniform(math.log(50), math.log(3000))))
        foods[fid] = Food(
            fid, f"{category.split()[0]} {fid}", category, tags.allergens, tags.animal, price
        )

    staple_ids = list(range(1, n_staples + 1))
    other_ids = list(range(n_staples + 1, n_foods + 1))
    recipes: dict[int, Recipe] = {}
    for rid in range(1, n_recipes + 1):
        meal_types, kind, lo, hi, _ = rng.choices(_KINDS, weights=[k[4] for k in _KINDS])[0]
        kcal = rng.randint(lo, hi)
        energy = kcal / rng.uniform(0.9, 1.1)  # what the macros add up to (Atwater)
        protein = rng.uniform(0.3, 0.45) if rng.random() < 0.3 else rng.uniform(0.08, 0.25)
        fat = rng.uniform(0.15, 0.45)
        carbs = 1 - protein - fat
        macros = Macros(
            kcal, round(energy * protein / 4), round(energy * fat / 9), round(energy * carbs / 4)
        )
        n_staple = min(rng.choice((0, 0, 1, 2)), len(staple_ids))
        n_other = min(rng.randint(3, 10) - n_staple, len(other_ids))
        ingredients = tuple(
            Ingredient(f, rng.randint(5, 100)) for f in rng.sample(other_ids, n_other)
        ) + tuple(Ingredient(f, 0) for f in rng.sample(staple_ids, n_staple))
        unresolved = rng.randint(1, 2) if rng.random() < 0.05 else 0
        text = _tags(rng) if rng.random() < 0.08 else FoodTags()
        cuisine = rng.choice(_CUISINES)
        recipes[rid] = Recipe(
            rid,
            f"{cuisine or 'Home'} {kind} {rid}",
            meal_types,
            macros,
            ingredients,
            unresolved=unresolved,
            text_allergens=text.allergens,
            text_animal=text.animal,
            cuisine=cuisine,
        )
    return Catalog(recipes, foods)


# --- shared pieces -------------------------------------------------------------------------------

_DIETS = (Diet.VEGETARIAN, Diet.VEGETARIAN, Diet.PESCATARIAN, Diet.VEGAN)
_ATTEMPTS = 20  # planted: fresh draws, the second half with the mildest profile


def _spec(slot: Slot, candidates: tuple[int, ...]) -> SlotSpec:
    required, lo, hi, repeats = SLOT_LIMITS[slot]
    return SlotSpec(slot, required, candidates, lo, hi, repeats)


def _taste(rng: Random, catalog: Catalog) -> TastePrefs:
    cuisines = sorted({r.cuisine for r in catalog.recipes.values() if r.cuisine})
    liked = rng.sample(cuisines, min(len(cuisines), rng.randint(0, 2)))
    others = [c for c in cuisines if c not in liked]
    disliked = rng.sample(others, min(len(others), rng.randint(0, 1)))
    food_ids = sorted(catalog.foods)
    return TastePrefs(
        frozenset(liked),
        frozenset(disliked),
        frozenset(rng.sample(food_ids, min(len(food_ids), rng.randint(0, 3)))),
        frozenset(rng.sample(food_ids, min(len(food_ids), rng.randint(0, 2)))),
    )


def _foods(
    pool: Mapping[int, Food], recipes: Mapping[int, Recipe], pantry: Sequence[Lot]
) -> dict[int, Food]:
    """The foods a problem references, as far as `pool` knows them."""
    ids = {i.food_id for r in recipes.values() for i in r.ingredients}
    ids |= {lot.food_id for lot in pantry}
    return {f: pool[f] for f in sorted(ids) if f in pool}


def _start(rng: Random) -> date:
    return START + timedelta(days=rng.randrange(7))


# --- planted -------------------------------------------------------------------------------------


def planted(seed: int, catalog: Catalog | None = None, *, days: int = 7, k: int = 40) -> Scenario:
    """A problem with a known valid plan. Profile: never empty, resampled (then made milder) until
    each required slot has enough allowed recipes for its repeat cap; candidates via `select`
    without pantry; per slot, 1-3 decoys (eligible but refused, preference 100) go first, their
    violation paths cycling with the seed. Slots: breakfast, lunch, dinner, and a snack in most
    seeds. The witness uses non-decoy candidates within caps and portion ranges, raised until
    every day reaches the 1,200 kcal floor; kcal bands, soft protein bands, budget (70% of
    seeds) and pantry lots (1-5 witness foods) are drawn around it.

    Raises RuntimeError if the catalogue can't support a scenario, or if the result fails
    `check_problem` or has a hard violation (a bug)."""
    rng = Random(seed)
    catalog = synthetic_catalog(seed) if catalog is None else catalog
    for attempt in range(_ATTEMPTS):
        scenario = _plant(rng, seed, catalog, days, k, mild=attempt >= _ATTEMPTS // 2)
        if scenario is not None:
            break
    else:
        raise RuntimeError(f"no planted scenario for seed {seed}: catalogue too small or narrow")
    assert scenario.witness is not None
    errors = check_problem(scenario.problem)
    violations = hard(validate(scenario.problem, scenario.witness))
    if errors or violations:
        raise RuntimeError(f"planted scenario {seed} is broken: {errors or violations}")
    return scenario


def _plant(
    rng: Random, seed: int, catalog: Catalog, days: int, k: int, *, mild: bool
) -> Scenario | None:
    slots = [s for s in SLOT_LIMITS if s is not Slot.SNACK or rng.random() < 0.8]
    counts = [rng.randint(1, 3) for _ in slots]
    paths = [list(DecoyPath)[(seed + i) % len(DecoyPath)] for i in range(sum(counts))]
    profile = _restrictions(rng, catalog, set(paths), mild=mild)
    shape = Problem(_start(rng), days, tuple(_spec(s, ()) for s in slots), {}, {}, Targets({}))
    if not _enough(catalog, profile, shape):
        return None

    protein_hint = Targets({}, {Nutrient.PROTEIN: Band(1, None)}) if rng.random() < 0.5 else None
    has_budget = rng.random() >= 0.3
    specs, recipes = select(
        catalog,
        profile,
        _taste(rng, catalog),
        (),
        [(s, SLOT_LIMITS[s][0]) for s in slots],
        targets=protein_hint,
        budget=0 if has_budget else None,  # select only asks whether there is one
        k=k,
        seed=seed,
    )

    safe = list(recipes.values())
    pool = dict(catalog.foods)
    decoys: dict[int, DecoyPath] = {}
    next_recipe = max(catalog.recipes, default=0) + 1
    next_food = max(catalog.foods, default=0) + 1
    path_queue = iter(paths)
    final: list[SlotSpec] = []
    for spec, count in zip(specs, counts, strict=True):
        bases = [recipes[r] for r in spec.candidates] or safe
        if not bases:
            return None
        ids: list[int] = []
        for _ in range(count):
            path = next(path_queue)
            made = _decoy(rng, rng.choice(bases), spec.slot, path, next_recipe, next_food, profile)
            if made is None:
                return None
            decoy, food = made
            if food is not None:
                pool[food.id] = food
            recipes[decoy.id] = decoy
            decoys[decoy.id] = path
            ids.append(decoy.id)
            next_recipe += 1
            next_food += 1
        final.append(_spec(spec.slot, (*ids, *spec.candidates)))

    problem = replace(shape, slots=tuple(final), recipes=recipes, foods=pool, profile=profile)
    witness = _witness(rng, problem, decoys)
    if witness is None:
        return None
    problem = replace(problem, targets=_around(rng, problem, witness))

    used = sorted(usage(problem, witness))
    chosen = rng.sample(used, min(len(used), rng.randint(1, 5)))
    pantry = tuple(
        Lot(f, rng.randint(20, 600), rng.choice([None, *range(-1, days + 3)])) for f in chosen
    )
    problem = replace(problem, pantry=pantry, foods=_foods(pool, recipes, pantry))
    if has_budget:
        cost = cost_millipence(problem, allocate(problem, witness).buy)
        problem = replace(problem, budget=to_minor(cost) + rng.randint(0, 500))
    return Scenario(problem, witness, decoys)


def _restrictions(rng: Random, catalog: Catalog, needs: set[DecoyPath], *, mild: bool) -> Profile:
    """A non-empty profile that refuses every decoy path in `needs`; `mild` keeps it to what the
    decoys need (one allergen, one avoided food, pescatarian)."""
    wants_allergen = int(bool(needs & {DecoyPath.FOOD_ALLERGEN, DecoyPath.TEXT_ALLERGEN}))
    wants_avoid = int(DecoyPath.AVOIDED in needs)
    n_allergens = wants_allergen if mild else max(wants_allergen, rng.choice((0, 1, 1, 2)))
    n_avoid = wants_avoid if mild else max(wants_avoid, rng.choice((0, 0, 1, 2)))
    if DecoyPath.TEXT_ANIMAL in needs:
        diet = Diet.PESCATARIAN if mild else rng.choice(_DIETS)
    else:
        diet = None if mild or rng.random() < 0.6 else rng.choice(_DIETS)
    if not (n_allergens or n_avoid or diet):
        n_allergens = 1
    priced = sorted(f.id for f in catalog.foods.values() if f.price_per_kg > 0)
    return Profile(
        frozenset(rng.sample(list(Allergen), n_allergens)),
        frozenset(rng.sample(priced, min(n_avoid, len(priced)))),
        diet,
    )


def _enough(catalog: Catalog, profile: Profile, shape: Problem) -> bool:
    """Whether the allowed recipes can fill every required slot within their repeat caps: each
    slot alone, and lunch and dinner together (they share recipes)."""
    required = [s.slot for s in shape.slots if s.required]
    mains = frozenset(required) & {Slot.LUNCH, Slot.DINNER}
    groups = [frozenset({s}) for s in required] + ([mains] if len(mains) > 1 else [])
    room = [0] * len(groups)
    for r in catalog.recipes.values():
        if allowed(r, catalog.foods, profile):
            cap = shape.repeat_cap(r)
            for g, group in enumerate(groups):
                room[g] += cap * bool(r.meal_types & group)
    return all(room[g] >= len(group) * shape.days for g, group in enumerate(groups))


def _decoy(
    rng: Random,
    base: Recipe,
    slot: Slot,
    path: DecoyPath,
    recipe_id: int,
    food_id: int,
    profile: Profile,
) -> tuple[Recipe, Food | None] | None:
    """A copy of `base` for `slot` that `profile` refuses by `path` alone (None if the profile
    has nothing for that path to break)."""
    decoy = replace(
        base,
        id=recipe_id,
        name=f"{base.name} ({path})",
        meal_types=frozenset({slot}),
        preference=100,
    )
    extra = Ingredient(food_id, rng.randint(5, 50))
    allergens = sorted(profile.allergens)
    if path in (DecoyPath.FOOD_ALLERGEN, DecoyPath.TEXT_ALLERGEN) and not allergens:
        return None
    if path is DecoyPath.FOOD_ALLERGEN:
        tags = FoodTags(frozenset({rng.choice(allergens)})).normalised()
        price = rng.randint(50, 3000)
        food = Food(food_id, f"Decoy food {food_id}", None, tags.allergens, tags.animal, price)
        return replace(decoy, ingredients=(*decoy.ingredients, extra)), food
    if path is DecoyPath.TEXT_ALLERGEN:
        return replace(decoy, text_allergens=decoy.text_allergens | {rng.choice(allergens)}), None
    if path is DecoyPath.TEXT_ANIMAL:
        if profile.diet is None:
            return None
        return replace(decoy, text_animal=decoy.text_animal | {AnimalTag.MEAT}), None
    if path is DecoyPath.AVOIDED:
        if not profile.avoid_food_ids:
            return None
        avoided = Ingredient(rng.choice(sorted(profile.avoid_food_ids)), rng.randint(5, 50))
        return replace(decoy, ingredients=(*decoy.ingredients, avoided)), None
    if path is DecoyPath.UNRESOLVED:
        return replace(decoy, unresolved=rng.randint(1, 3)), None
    return replace(decoy, ingredients=(*decoy.ingredients, extra)), None  # food never added


_FILL_ORDER = (Slot.BREAKFAST, Slot.DINNER, Slot.LUNCH, Slot.SNACK)  # dinner has fewer options


def _witness(rng: Random, problem: Problem, decoys: Mapping[int, DecoyPath]) -> Plan | None:
    uses: Counter[int] = Counter()
    meals: dict[tuple[int, Slot], Meal] = {}

    def options(spec: SlotSpec) -> list[int]:
        return [
            r
            for r in spec.candidates
            if r not in decoys and uses[r] < problem.repeat_cap(problem.recipes[r])
        ]

    def add(day: int, spec: SlotSpec, portions: int | None = None) -> bool:
        choices = options(spec)
        if not choices:
            return False
        rid = rng.choice(choices)
        lo, hi = problem.portion_range(spec.slot)
        meals[(day, spec.slot)] = Meal(day, spec.slot, rid, portions or rng.randint(lo, hi))
        uses[rid] += 1
        return True

    specs = sorted(problem.slots, key=lambda s: _FILL_ORDER.index(s.slot))
    for day in range(problem.days):
        for spec in specs:
            if not spec.required and rng.random() >= 0.5:
                continue
            if not add(day, spec) and spec.required:
                return None
        while _kcal(problem, meals, day) < FLOOR:
            growable = [
                m
                for m in meals.values()
                if m.day == day and m.portions < problem.portion_range(m.slot)[1]
            ]
            snack = problem.spec(Slot.SNACK)
            if growable:
                meal = max(growable, key=lambda g: problem.recipes[g.recipe_id].per_portion.kcal)
                meals[(day, meal.slot)] = replace(meal, portions=meal.portions + 1)
            elif (
                snack is None
                or (day, Slot.SNACK) in meals
                or not add(day, snack, problem.portion_range(Slot.SNACK)[0])
            ):
                return None
    return Plan(tuple(sorted(meals.values(), key=lambda m: (m.day, SLOT_ORDER.index(m.slot)))))


def _kcal(problem: Problem, meals: Mapping[tuple[int, Slot], Meal], day: int) -> int:
    return sum(
        problem.recipes[m.recipe_id].per_portion.kcal * m.portions
        for m in meals.values()
        if m.day == day
    )


def _around(rng: Random, problem: Problem, witness: Plan) -> Targets:
    """Targets the witness meets: a hard kcal band (and sometimes a weekly one) containing every
    day, and soft protein/fat bands drawn near it (which it may miss)."""
    totals = day_totals(problem, witness)
    kcal = [t.kcal for t in totals]
    protein = [t.protein_g for t in totals]
    daily = {
        Nutrient.KCAL: Band(rng.randint(FLOOR, min(kcal)), rng.randint(max(kcal), max(kcal) + 300))
    }
    low = round(min(protein) * rng.uniform(0.85, 1.1))
    daily[Nutrient.PROTEIN] = Band(low, max(low, round(max(protein) * rng.uniform(0.95, 1.2))))
    if rng.random() < 0.3:
        fat = max(t.fat_g for t in totals)
        daily[Nutrient.FAT] = Band(None, round(fat * rng.uniform(0.9, 1.3)))
    week = sum(totals, Macros())
    weekly: dict[Nutrient, Band] = {}
    if rng.random() < 0.5:
        weekly[Nutrient.PROTEIN] = Band(round(week.protein_g * rng.uniform(0.9, 1.05)), None)
    if rng.random() < 0.5:
        weekly[Nutrient.KCAL] = Band(
            week.kcal - rng.randint(0, 700), week.kcal + rng.randint(0, 700)
        )
    return Targets(daily, weekly, calorie_floor=FLOOR)


# --- infeasible and realistic --------------------------------------------------------------------


def infeasible(seed: int, catalog: Catalog | None = None) -> Scenario:
    """`planted(seed, catalog)` with a daily kcal band just beyond reach: Band(R + 1, R + 500),
    R = the most kcal any day can hold (every slot's biggest candidate, decoys included, at max
    portions, plus locked meals and extra)."""
    base = planted(seed, catalog)
    p = base.problem
    reach = max(_reach(p, day) for day in range(p.days))
    daily = {**p.targets.daily, Nutrient.KCAL: Band(reach + 1, reach + 500)}
    return Scenario(replace(p, targets=replace(p.targets, daily=daily)), None, base.decoys)


def _reach(problem: Problem, day: int) -> int:
    total = problem.extra.get(day, Macros()).kcal
    for spec in problem.slots:
        if (day, spec.slot) in problem.locked:
            lock = problem.locked[(day, spec.slot)]
            if lock is not None and lock.recipe_id in problem.recipes:
                total += problem.recipes[lock.recipe_id].per_portion.kcal * lock.portions
            continue
        _, hi = problem.portion_range(spec.slot)
        kcal = [
            problem.recipes[r].per_portion.kcal for r in spec.candidates if r in problem.recipes
        ]
        total += max(kcal, default=0) * hi
    return total


_KCAL_BANDS = ((1400, 1600), (1600, 1800), (1800, 2000), (2000, 2300), (2400, 2700))


def realistic(seed: int, catalog: Catalog, *, days: int = 7, k: int = 40) -> Scenario:
    """A user-like problem for the bench: an allergen or two (45% of seeds), a diet (25%), avoided
    foods (15%), or none of these; kcal bands like 1,400-1,600 or 2,400-2,700; protein 1.2-1.6
    g/kg (capped at 30% of kcal) and fat 20-35% of kcal as soft bands; a budget (60%); a few
    pantry lots; four slots. Nothing guarantees a plan exists."""
    rng = Random(seed)
    restricted = rng.random() < 0.45
    profile = Profile(
        frozenset(rng.sample(list(Allergen), rng.choice((1, 1, 2)))) if restricted else frozenset(),
        frozenset(rng.sample(sorted(catalog.foods), min(2, len(catalog.foods))))
        if rng.random() < 0.15
        else frozenset(),
        rng.choice(_DIETS) if rng.random() < 0.25 else None,
    )
    lo, hi = rng.choice(_KCAL_BANDS)
    weight_kg = hi / 28 * rng.uniform(0.85, 1.15)
    protein = min(round(weight_kg * rng.uniform(1.2, 1.6)), round(0.3 * hi / 4))
    fat_lo, fat_hi = round(0.2 * lo / 9), round(0.35 * hi / 9)
    targets = Targets(
        daily={
            Nutrient.KCAL: Band(lo, hi),
            Nutrient.PROTEIN: Band(round(0.8 * protein), round(1.25 * 1.5 * protein)),
            Nutrient.FAT: Band(round(0.8 * fat_lo), round(1.25 * fat_hi)),
        },
        weekly={
            Nutrient.PROTEIN: Band(days * protein, days * round(1.5 * protein)),
            Nutrient.FAT: Band(days * fat_lo, days * fat_hi),
        },
        calorie_floor=FLOOR,
    )
    budget = None if rng.random() < 0.4 else rng.randint(3500, 9000) * days // 7
    weighed = sorted(
        {
            i.food_id
            for r in catalog.recipes.values()
            for i in r.ingredients
            if i.grams > 0 and i.food_id in catalog.foods
        }
    )
    pantry = tuple(
        Lot(f, rng.randint(50, 1000), None if rng.random() < 0.4 else rng.randint(0, days + 3))
        for f in rng.sample(weighed, min(len(weighed), rng.randint(3, 12)))
    )
    specs, recipes = select(
        catalog,
        profile,
        _taste(rng, catalog),
        pantry,
        [(s, SLOT_LIMITS[s][0]) for s in SLOT_LIMITS],
        targets=targets,
        budget=budget,
        k=k,
        seed=seed,
    )
    problem = Problem(
        start=_start(rng),
        days=days,
        slots=tuple(_spec(s.slot, s.candidates) for s in specs),
        recipes=recipes,
        foods=_foods(catalog.foods, recipes, pantry),
        targets=targets,
        profile=profile,
        pantry=pantry,
        budget=budget,
    )
    return Scenario(problem, None)
