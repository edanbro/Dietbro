"""Candidate prefilter (PLAN §6): per slot, the k recipes the planner may choose from.

A small candidate set keeps the model fast. Per slot, the pool is every recipe that passes the
hard filters (written independently of the validator, which re-checks every plan) and fits the
slot. It is filled in order:

(a) with a protein minimum in the targets, the ceil(k/4) recipes with the most protein per kcal;
(b) with a budget, the ceil(k/8) cheapest per kcal of the rest;
(c) the rest by preference, minus 30 for recipes in `novelty` (last plan's), plus a pantry bonus
    of 0..30 (the share of a portion's grams the pantry covers, grams in lots expiring within 3
    days counting double). A cuisine (compared case-insensitively) may take at most k // 4 of
    these places until nothing else is left.

Reserves (a) and (b) keep the targets reachable for new users whose ranking is otherwise only
the seeded hash. Ties break on a hash of (seed, recipe id), so the result is deterministic per
seed and varies across seeds.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from hashlib import blake2b

from larder_core.tagging import diet_allows
from larder_solver.problem import (
    Catalog,
    Food,
    Lot,
    Nutrient,
    Profile,
    Recipe,
    Slot,
    SlotSpec,
    Targets,
)

SOON_DAYS = 3  # grams in lots that expire before day SOON_DAYS count double in the pantry bonus


@dataclass(frozen=True, slots=True)
class TastePrefs:
    liked_cuisines: frozenset[str] = frozenset()
    disliked_cuisines: frozenset[str] = frozenset()
    liked_food_ids: frozenset[int] = frozenset()
    disliked_food_ids: frozenset[int] = frozenset()


def allowed(recipe: Recipe, foods: Mapping[int, Food], profile: Profile) -> bool:
    """Whether `recipe` is safe for `profile`: every ingredient food is known and not avoided, no
    allergen (from foods or text), the diet allows its animal products, and an unverified recipe
    only for a user with no restrictions."""
    if recipe.unresolved > 0 and profile.restricted:
        return False
    allergens = set(recipe.text_allergens)
    animal = set(recipe.text_animal)
    for ingredient in recipe.ingredients:
        food = foods.get(ingredient.food_id)
        if food is None or ingredient.food_id in profile.avoid_food_ids:
            return False
        allergens |= food.allergens
        animal |= food.animal
    return not allergens & profile.allergens and diet_allows(profile.diet, frozenset(animal))


def preference(recipe: Recipe, prefs: TastePrefs) -> int:
    """-100..100: +40 liked cuisine, -60 disliked cuisine, +15 per liked food (at most +45), -40
    per disliked food (at most -80). Cuisines compare case-insensitively."""
    cuisine = (recipe.cuisine or "").casefold()
    food_ids = {i.food_id for i in recipe.ingredients}
    points = min(15 * len(food_ids & prefs.liked_food_ids), 45)
    points -= min(40 * len(food_ids & prefs.disliked_food_ids), 80)
    if cuisine and cuisine in {c.casefold() for c in prefs.liked_cuisines}:
        points += 40
    if cuisine and cuisine in {c.casefold() for c in prefs.disliked_cuisines}:
        points -= 60
    return max(-100, min(100, points))


def _tiebreak(seed: int, recipe_id: int) -> int:
    return int.from_bytes(blake2b(f"{seed}:{recipe_id}".encode(), digest_size=8).digest())


def _pantry_bonus(recipe: Recipe, stock: Mapping[int, tuple[int, int]]) -> int:
    """0..30: 30 x the share of a portion's grams the pantry covers, drawing on lots expiring
    soon first and counting those grams double, capped at the whole portion."""
    need: Counter[int] = Counter()
    for i in recipe.ingredients:
        need[i.food_id] += max(i.grams, 0)
    total = sum(need.values())
    if total == 0:
        return 0
    covered = 0
    for food_id, grams in need.items():
        soon, later = stock.get(food_id, (0, 0))
        from_soon = min(grams, soon)
        covered += 2 * from_soon + min(grams - from_soon, later)
    return 30 * min(covered, total) // total


def _protein_min(targets: Targets | None) -> bool:
    if targets is None:
        return False
    bands = (targets.daily.get(Nutrient.PROTEIN), targets.weekly.get(Nutrient.PROTEIN))
    return any(b is not None and b.min is not None for b in bands)


def select(
    catalog: Catalog,
    profile: Profile,
    prefs: TastePrefs,
    pantry: Sequence[Lot],
    slots: Sequence[tuple[Slot, bool]],
    *,
    targets: Targets | None = None,
    budget: int | None = None,
    novelty: frozenset[int] = frozenset(),
    k: int = 40,
    seed: int = 0,
) -> tuple[tuple[SlotSpec, ...], dict[int, Recipe]]:
    """Candidates per (slot, required), in `slots` order and fill order (best first), and every
    candidate recipe with its `preference` set. Spec portion ranges and repeat caps are left
    None for the caller to set; a slot with no allowed recipe gets no candidates."""
    k = max(k, 0)
    ok = [
        replace(r, preference=preference(r, prefs))
        for r in catalog.recipes.values()
        if allowed(r, catalog.foods, profile)
    ]
    soon: Counter[int] = Counter()  # grams per food in lots usable only on the first days
    later: Counter[int] = Counter()
    for lot in pantry:
        if lot.expires is None or lot.expires >= SOON_DAYS:
            later[lot.food_id] += max(lot.grams, 0)
        elif lot.expires >= 0:
            soon[lot.food_id] += max(lot.grams, 0)
    stock = {f: (soon[f], later[f]) for f in soon.keys() | later.keys()}
    bonus = {r.id: _pantry_bonus(r, stock) for r in ok}

    def tiebreak(r: Recipe) -> tuple[int, int]:
        return _tiebreak(seed, r.id), r.id

    def protein(r: Recipe) -> Fraction:
        return Fraction(r.per_portion.protein_g, max(r.per_portion.kcal, 1))

    def price(r: Recipe) -> Fraction:
        cost = sum(i.grams * catalog.foods[i.food_id].price_per_kg for i in r.ingredients)
        return Fraction(cost, max(r.per_portion.kcal, 1))

    def rank(r: Recipe) -> int:
        return -(r.preference - 30 * (r.id in novelty) + bonus[r.id])

    specs: list[SlotSpec] = []
    chosen: dict[int, Recipe] = {}
    for slot, required in slots:
        pool = [r for r in ok if slot in r.meal_types]
        picks: list[Recipe] = []
        if _protein_min(targets):
            picks += sorted(pool, key=lambda r: (-protein(r), *tiebreak(r)))[: -(-k // 4)]
        if budget is not None:
            taken = {r.id for r in picks}
            cheap = [r for r in pool if r.id not in taken]
            picks += sorted(cheap, key=lambda r: (price(r), *tiebreak(r)))[: -(-k // 8)]
        picks = picks[:k]
        taken = {r.id for r in picks}
        rest = [r for r in pool if r.id not in taken]
        waiting: list[Recipe] = []
        per_cuisine: Counter[str] = Counter()
        for r in sorted(rest, key=lambda r: (rank(r), *tiebreak(r))):
            if len(picks) == k:
                break
            cuisine = r.cuisine.casefold() if r.cuisine else None
            if cuisine is None or per_cuisine[cuisine] < k // 4:
                picks.append(r)
                if cuisine is not None:
                    per_cuisine[cuisine] += 1
            else:
                waiting.append(r)
        picks += waiting[: k - len(picks)]
        specs.append(SlotSpec(slot, required, tuple(r.id for r in picks)))
        chosen.update((r.id, r) for r in picks)
    return tuple(specs), chosen
