import os
import subprocess
import sys

import pytest

from larder_solver.candidates import allowed
from larder_solver.metrics import allocate, cost_millipence, day_totals, to_minor
from larder_solver.problem import (
    Band,
    Catalog,
    Macros,
    Meal,
    Nutrient,
    Plan,
    Problem,
    Slot,
    check_problem,
)
from larder_solver.scenarios import DecoyPath, infeasible, planted, realistic, synthetic_catalog
from larder_solver.validate import Code, hard, validate

B, L, D, S = Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER, Slot.SNACK
CATALOG = synthetic_catalog(0)

KCAL_RANGES: dict[frozenset[Slot], tuple[int, int]] = {
    frozenset({B}): (150, 250),
    frozenset({L, D}): (250, 380),
    frozenset({L}): (120, 220),
    frozenset({S}): (80, 200),
    frozenset({B, S}): (150, 200),
}
PATH_CODES = {
    DecoyPath.FOOD_ALLERGEN: Code.ALLERGEN,
    DecoyPath.TEXT_ALLERGEN: Code.ALLERGEN,
    DecoyPath.TEXT_ANIMAL: Code.DIET,
    DecoyPath.AVOIDED: Code.AVOIDED,
    DecoyPath.UNRESOLVED: Code.UNVERIFIED,
    DecoyPath.UNKNOWN_FOOD: Code.UNKNOWN_FOOD,
}


# --- synthetic catalogue -------------------------------------------------------------------------


def test_catalog_is_deterministic_and_sized() -> None:
    assert synthetic_catalog(0) == CATALOG
    assert synthetic_catalog(1) != CATALOG
    assert (len(CATALOG.recipes), len(CATALOG.foods)) == (300, 150)
    small = synthetic_catalog(5, n_recipes=40, n_foods=30)
    assert (len(small.recipes), len(small.foods)) == (40, 30)


@pytest.mark.parametrize("seed", range(3))
def test_catalog_recipes_are_plausible(seed: int) -> None:
    cat = synthetic_catalog(seed)
    for r in cat.recipes.values():
        m = r.per_portion
        atwater = 4 * m.protein_g + 9 * m.fat_g + 4 * m.carbs_g
        assert abs(m.kcal - atwater) <= 0.1 * atwater + 10
        lo, hi = KCAL_RANGES[r.meal_types]
        assert lo <= m.kcal <= hi
        assert 3 <= len(r.ingredients) <= 10
        assert len({i.food_id for i in r.ingredients}) == len(r.ingredients)
        assert all(i.food_id in cat.foods for i in r.ingredients)
        for i in r.ingredients:
            assert (i.grams == 0) == (cat.foods[i.food_id].price_per_kg == 0)
        assert any(i.grams > 0 for i in r.ingredients)
    recipes = list(cat.recipes.values())
    for kind in (frozenset({B}), frozenset({L, D}), frozenset({S})):
        of_kind = [r for r in recipes if r.meal_types == kind]
        high = [r for r in of_kind if 4 * r.per_portion.protein_g >= 0.3 * r.per_portion.kcal]
        assert len(high) >= 3, kind
    assert sum(any(i.grams == 0 for i in r.ingredients) for r in recipes) >= 50
    assert 3 <= sum(r.unresolved > 0 for r in recipes) <= 40
    assert sum(bool(r.text_allergens or r.text_animal) for r in recipes) >= 5


@pytest.mark.parametrize("seed", range(3))
def test_catalog_foods_are_plausible(seed: int) -> None:
    foods = list(synthetic_catalog(seed).foods.values())
    tagged = sum(bool(f.allergens or f.animal) for f in foods)
    assert 0.08 <= tagged / len(foods) <= 0.25
    assert any(f.price_per_kg == 0 for f in foods)
    assert all(f.price_per_kg == 0 or 50 <= f.price_per_kg <= 3000 for f in foods)


# --- planted -------------------------------------------------------------------------------------


def witness_foods(problem: Problem, plan: Plan) -> set[int]:
    return {
        i.food_id
        for m in plan.meals
        for i in problem.recipes[m.recipe_id].ingredients
        if i.grams > 0
    }


@pytest.mark.parametrize("seed", range(100))
def test_planted_invariants(seed: int) -> None:
    s = planted(seed)
    p, w = s.problem, s.witness
    assert w is not None
    assert check_problem(p) == []
    assert hard(validate(p, w)) == []
    assert p.days == 7
    assert p.profile.restricted

    specs = {spec.slot: spec for spec in p.slots}
    assert [spec.slot for spec in p.slots][:3] == [B, L, D]
    limits = {
        spec.slot: (spec.required, *p.portion_range(spec.slot), spec.max_repeats)
        for spec in p.slots
    }
    assert limits[B] == (True, 1, 3, 4)
    assert limits[L] == (True, 1, 4, None)
    assert limits[D] == (True, 2, 4, None)
    assert limits.get(S, (False, 1, 2, 4)) == (False, 1, 2, 4)

    for spec in p.slots:
        decoys = [rid for rid in spec.candidates if rid in s.decoys]
        assert 1 <= len(decoys) <= 3
        assert spec.candidates[: len(decoys)] == tuple(decoys)  # prepended
        lo, _ = p.portion_range(spec.slot)
        for rid in decoys:
            r = p.recipes[rid]
            assert r.preference == 100
            assert spec.slot in r.meal_types
            assert not allowed(r, p.foods, p.profile)
            found = validate(p, Plan((Meal(0, spec.slot, rid, lo),)))
            assert PATH_CODES[s.decoys[rid]] in {v.code for v in found}
        others = [p.recipes[rid] for rid in spec.candidates if rid not in s.decoys]
        assert all(allowed(r, p.foods, p.profile) for r in others)
        assert len(others) <= 40

    for m in w.meals:
        assert m.recipe_id not in s.decoys
        assert m.recipe_id in specs[m.slot].candidates
    assert {(m.day, m.slot) for m in w.meals} >= {(d, x) for d in range(7) for x in (B, L, D)}

    assert p.targets.calorie_floor == 1200
    kcal = [t.kcal for t in day_totals(p, w)]
    assert min(kcal) >= 1200
    band = p.targets.daily[Nutrient.KCAL]
    assert band.min is not None
    assert band.max is not None
    assert 1200 <= band.min <= min(kcal) <= max(kcal) <= band.max <= max(kcal) + 300
    assert Nutrient.PROTEIN in p.targets.daily

    if p.budget is not None:
        assert p.budget >= to_minor(cost_millipence(p, allocate(p, w).buy))
    assert 1 <= len(p.pantry) <= 5
    for lot in p.pantry:
        assert lot.food_id in witness_foods(p, w)
        assert lot.expires is None or -1 <= lot.expires <= p.days + 2

    referenced = {i.food_id for r in p.recipes.values() for i in r.ingredients}
    assert set(p.foods) <= referenced | {lot.food_id for lot in p.pantry}
    for rid, r in p.recipes.items():
        if any(i.food_id not in p.foods for i in r.ingredients):
            assert s.decoys.get(rid) is DecoyPath.UNKNOWN_FOOD


def test_decoys_cycle_through_every_violation_path() -> None:
    seen = {path for seed in range(6) for path in planted(seed).decoys.values()}
    assert seen == set(DecoyPath)


def test_text_only_decoys_have_clean_ingredients() -> None:
    for seed in range(12):
        s = planted(seed)
        p = s.problem
        for rid, path in s.decoys.items():
            r = p.recipes[rid]
            foods = [p.foods[i.food_id] for i in r.ingredients if i.food_id in p.foods]
            food_allergens = {a for f in foods for a in f.allergens}
            if path is DecoyPath.TEXT_ALLERGEN:
                assert not food_allergens & p.profile.allergens
                assert r.text_allergens & p.profile.allergens
            if path is DecoyPath.FOOD_ALLERGEN:
                assert food_allergens & p.profile.allergens


def test_planted_is_deterministic() -> None:
    assert planted(11) == planted(11)
    assert planted(11) != planted(12)


@pytest.mark.parametrize(("days", "k"), [(1, 10), (3, 10), (14, 40)])
def test_planted_sizes(days: int, k: int) -> None:
    for seed in range(5):
        s = planted(seed, CATALOG, days=days, k=k)
        assert s.witness is not None
        assert s.problem.days == days
        assert check_problem(s.problem) == []
        assert hard(validate(s.problem, s.witness)) == []
        for spec in s.problem.slots:
            assert len([r for r in spec.candidates if r not in s.decoys]) <= k


@pytest.mark.parametrize("seed", range(5))
def test_planted_relaxes_restrictions_on_a_small_catalog(seed: int) -> None:
    s = planted(seed, synthetic_catalog(seed, n_recipes=60, n_foods=40))
    assert s.witness is not None
    assert s.problem.profile.restricted
    assert hard(validate(s.problem, s.witness)) == []


def test_planted_refuses_an_impossible_catalog() -> None:
    mains = {rid: r for rid, r in CATALOG.recipes.items() if B not in r.meal_types}
    with pytest.raises(RuntimeError, match="seed 0"):
        planted(0, Catalog(mains, CATALOG.foods))


# --- infeasible and realistic --------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(10))
def test_infeasible_band_is_beyond_reach(seed: int) -> None:
    s = infeasible(seed)
    p = s.problem
    assert s.witness is None
    assert check_problem(p) == []
    base = planted(seed).problem
    assert (p.slots, p.recipes, p.profile) == (base.slots, base.recipes, base.profile)
    biggest: list[Meal] = []
    for spec in p.slots:
        _, hi = p.portion_range(spec.slot)
        rid = max(spec.candidates, key=lambda r: p.recipes[r].per_portion.kcal)
        biggest += [Meal(d, spec.slot, rid, hi) for d in range(p.days)]
    band = p.targets.daily[Nutrient.KCAL]
    assert band.min is not None
    reach = max(t.kcal for t in day_totals(p, Plan(tuple(biggest))))
    assert band == Band(reach + 1, reach + 500)
    found = validate(p, Plan(tuple(biggest)))
    assert sum(v.code is Code.DAILY_BAND and v.hard for v in found) == p.days


@pytest.mark.parametrize("seed", range(5))
def test_realistic(seed: int) -> None:
    s = realistic(seed, CATALOG)
    p = s.problem
    assert s.witness is None
    assert s == realistic(seed, CATALOG)
    assert check_problem(p) == []
    assert [(spec.slot, spec.required) for spec in p.slots] == [
        (B, True),
        (L, True),
        (D, True),
        (S, False),
    ]
    kcal = p.targets.daily[Nutrient.KCAL]
    assert kcal.min is not None
    assert kcal.max is not None
    assert 1400 <= kcal.min < kcal.max <= 2700
    assert p.targets.weekly[Nutrient.PROTEIN].min is not None
    for spec in p.slots:
        assert 0 < len(spec.candidates) <= 40
        assert all(allowed(p.recipes[r], p.foods, p.profile) for r in spec.candidates)
    assert all(lot.food_id in p.foods for lot in p.pantry)
    assert p.extra == {} or all(isinstance(m, Macros) for m in p.extra.values())


# --- determinism across processes ----------------------------------------------------------------

_DIGEST = """
import hashlib, json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date
from enum import Enum

from larder_solver.scenarios import infeasible, planted, realistic, synthetic_catalog

def canon(x):
    if is_dataclass(x) and not isinstance(x, type):
        return {f.name: canon(getattr(x, f.name)) for f in fields(x)}
    if isinstance(x, Mapping):
        return sorted(([canon(k), canon(v)] for k, v in x.items()), key=json.dumps)
    if isinstance(x, (set, frozenset)):
        return sorted((canon(v) for v in x), key=json.dumps)
    if isinstance(x, (list, tuple)):
        return [canon(v) for v in x]
    if isinstance(x, Enum):
        return x.value
    if isinstance(x, date):
        return x.isoformat()
    return x

out = [planted(3), infeasible(4), realistic(5, synthetic_catalog(6))]
print(hashlib.sha256(json.dumps(canon(out)).encode()).hexdigest())
"""


def test_scenarios_do_not_depend_on_hash_randomisation() -> None:
    digests = {
        subprocess.run(
            [sys.executable, "-c", _DIGEST],
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for hash_seed in ("1", "2")
    }
    assert len(digests) == 1
