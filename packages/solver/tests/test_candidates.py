from collections import Counter
from collections.abc import Sequence
from datetime import date
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from larder_solver.candidates import TastePrefs, allowed, preference, select
from larder_solver.problem import (
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
)
from larder_solver.scenarios import synthetic_catalog
from larder_solver.validate import HARD_FILTER_CODES, validate

B, L, D, S = Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER, Slot.SNACK
MAINS = frozenset({L, D})
FOUR_SLOTS = ((B, True), (L, True), (D, True), (S, False))
CATALOG = synthetic_catalog(0)
NO_PREFS = TastePrefs()
OPEN = Profile()
MACROS = Macros(300, 20, 10, 30)

FOODS = {
    f.id: f
    for f in (
        Food(1, "rice", price_per_kg=300),
        Food(2, "peanuts", allergens=frozenset({Allergen.PEANUTS}), price_per_kg=800),
        Food(3, "beef", animal=frozenset({AnimalTag.MEAT}), price_per_kg=900),
        Food(4, "beans", price_per_kg=400),
        Food(5, "salt"),
    )
}


def rec(
    rid: int,
    *ingredients: tuple[int, int],
    slots: frozenset[Slot] = MAINS,
    macros: Macros = MACROS,
    cuisine: str | None = None,
    unresolved: int = 0,
    text_allergens: frozenset[Allergen] = frozenset(),
    text_animal: frozenset[AnimalTag] = frozenset(),
) -> Recipe:
    return Recipe(
        rid,
        f"Recipe {rid}",
        slots,
        macros,
        tuple(Ingredient(f, g) for f, g in ingredients),
        unresolved=unresolved,
        text_allergens=text_allergens,
        text_animal=text_animal,
        cuisine=cuisine,
    )


def catalog(recipes: Sequence[Recipe]) -> Catalog:
    return Catalog({r.id: r for r in recipes}, FOODS)


# --- hard filters --------------------------------------------------------------------------------

STRICT = Profile(
    allergens=frozenset({Allergen.PEANUTS}), avoid_food_ids=frozenset({4}), diet=Diet.VEGETARIAN
)


@pytest.mark.parametrize(
    ("recipe", "ok"),
    [
        (rec(1, (1, 100), (5, 0)), True),
        (rec(1, (1, 100), (2, 0)), False),  # allergen, even as a 0 g staple
        (rec(1, (1, 100), text_allergens=frozenset({Allergen.PEANUTS})), False),
        (rec(1, (1, 100), (3, 50)), False),  # meat
        (rec(1, (1, 100), text_animal=frozenset({AnimalTag.MEAT})), False),
        (rec(1, (1, 100), text_animal=frozenset({AnimalTag.DAIRY})), True),  # vegetarian is fine
        (rec(1, (1, 100), (4, 10)), False),  # avoided
        (rec(1, (1, 100), unresolved=1), False),
        (rec(1, (1, 100), (404, 10)), False),  # unknown food
    ],
)
def test_allowed(recipe: Recipe, ok: bool) -> None:
    assert allowed(recipe, FOODS, STRICT) is ok


def test_without_restrictions_only_unknown_foods_are_refused() -> None:
    assert allowed(rec(1, (2, 10), (3, 10), unresolved=2), FOODS, OPEN)
    assert not allowed(rec(1, (1, 10), (404, 10)), FOODS, OPEN)


profiles = st.builds(
    Profile,
    allergens=st.frozensets(st.sampled_from(Allergen), max_size=3),
    avoid_food_ids=st.frozensets(st.sampled_from(sorted(CATALOG.foods)), max_size=4),
    diet=st.none() | st.sampled_from(Diet),
)


@settings(max_examples=40)
@given(profiles, st.frozensets(st.sampled_from(sorted(CATALOG.foods)), max_size=8))
def test_prefilter_agrees_with_the_validator(profile: Profile, dropped: frozenset[int]) -> None:
    foods = {f: food for f, food in CATALOG.foods.items() if f not in dropped}
    problem = Problem(
        start=date(2026, 1, 5),
        days=1,
        slots=(SlotSpec(L, True, ()),),
        recipes=CATALOG.recipes,
        foods=foods,
        targets=Targets(daily={}, calorie_floor=0),
        profile=profile,
    )
    lo, _ = problem.portion_range(L)
    for r in CATALOG.recipes.values():
        found = validate(problem, Plan((Meal(0, L, r.id, lo),)))
        assert allowed(r, foods, profile) == (not any(v.code in HARD_FILTER_CODES for v in found))


small_profiles = st.builds(
    Profile,
    allergens=st.frozensets(st.sampled_from(Allergen), max_size=3),
    avoid_food_ids=st.frozensets(st.integers(1, 8), max_size=2),
    diet=st.none() | st.sampled_from(Diet),
)
tagged_foods = st.dictionaries(
    st.integers(1, 6),
    st.tuples(
        st.frozensets(st.sampled_from(Allergen), max_size=2),
        st.frozensets(st.sampled_from(AnimalTag), max_size=2),
    ),
)
random_recipes = st.builds(
    Recipe,
    id=st.just(1),
    name=st.just("Recipe 1"),
    meal_types=st.just(MAINS),
    per_portion=st.just(MACROS),
    ingredients=st.lists(
        st.builds(Ingredient, st.integers(1, 8), st.integers(0, 50)), max_size=5
    ).map(tuple),
    unresolved=st.integers(0, 2),
    text_allergens=st.frozensets(st.sampled_from(Allergen), max_size=2),
    text_animal=st.frozensets(st.sampled_from(AnimalTag), max_size=2),
)


@given(small_profiles, tagged_foods, random_recipes)
def test_prefilter_agrees_with_the_validator_on_arbitrary_recipes(
    profile: Profile,
    tags: dict[int, tuple[frozenset[Allergen], frozenset[AnimalTag]]],
    r: Recipe,
) -> None:
    # Foods 7 and 8 never exist; tags are arbitrary (not normalised), lines may repeat a food.
    foods = {f: Food(f, f"food {f}", None, a, t, 100) for f, (a, t) in tags.items()}
    problem = Problem(
        start=date(2026, 1, 5),
        days=1,
        slots=(SlotSpec(L, True, (1,)),),
        recipes={1: r},
        foods=foods,
        targets=Targets(daily={}, calorie_floor=0),
        profile=profile,
    )
    found = validate(problem, Plan((Meal(0, L, 1, 1),)))
    assert allowed(r, foods, profile) == (not any(v.code in HARD_FILTER_CODES for v in found))


@pytest.mark.parametrize(
    "profile",
    [
        OPEN,
        Profile(allergens=frozenset({Allergen.MILK, Allergen.GLUTEN})),
        Profile(diet=Diet.VEGAN),
        Profile(avoid_food_ids=frozenset(list(CATALOG.foods)[:20]), diet=Diet.PESCATARIAN),
    ],
)
def test_select_never_returns_a_disallowed_or_ineligible_recipe(profile: Profile) -> None:
    specs, recipes = select(CATALOG, profile, NO_PREFS, (), FOUR_SLOTS, k=40)
    for spec in specs:
        assert len(set(spec.candidates)) == len(spec.candidates)
        for rid in spec.candidates:
            assert allowed(recipes[rid], CATALOG.foods, profile)
            assert spec.slot in recipes[rid].meal_types
    assert set(recipes) == {rid for spec in specs for rid in spec.candidates}


# --- preference ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prefs", "expected"),
    [
        (TastePrefs(liked_cuisines=frozenset({"Thai"})), 40),
        (TastePrefs(liked_cuisines=frozenset({"thai"})), 40),
        (TastePrefs(disliked_cuisines=frozenset({"Thai"})), -60),
        (TastePrefs(liked_food_ids=frozenset({1})), 15),
        (TastePrefs(liked_food_ids=frozenset({1, 2, 3})), 45),
        (TastePrefs(liked_food_ids=frozenset({1, 2, 3, 4})), 45),
        (TastePrefs(disliked_food_ids=frozenset({1})), -40),
        (TastePrefs(disliked_food_ids=frozenset({1, 2, 3})), -80),
        (TastePrefs(frozenset({"Thai"}), frozenset(), frozenset({1, 2, 3, 4})), 85),
        (TastePrefs(frozenset(), frozenset({"Thai"}), frozenset(), frozenset({1, 2, 3})), -100),
        (TastePrefs(frozenset({"Thai"}), frozenset(), frozenset({1}), frozenset({2})), 15),
        (TastePrefs(liked_cuisines=frozenset({"Greek"})), 0),
    ],
)
def test_preference_arithmetic(prefs: TastePrefs, expected: int) -> None:
    r = rec(1, (1, 10), (1, 5), (2, 10), (3, 10), (4, 0), cuisine="Thai")
    assert preference(r, prefs) == expected


def test_select_sets_preference_and_leaves_spec_limits_to_the_caller() -> None:
    prefs = TastePrefs(liked_cuisines=frozenset({"Thai"}), disliked_food_ids=frozenset({4}))
    cat = catalog([rec(1, (1, 10), cuisine="Thai"), rec(2, (4, 10)), rec(3, slots=frozenset({B}))])
    specs, recipes = select(cat, OPEN, prefs, (), [(D, True), (S, False), (B, True)])
    assert [(s.slot, s.required) for s in specs] == [(D, True), (S, False), (B, True)]
    assert specs[1].candidates == ()
    assert {rid: r.preference for rid, r in recipes.items()} == {1: 40, 2: -40, 3: 0}
    assert specs[0].candidates == (1, 2)
    for s in specs:
        assert (s.min_portions, s.max_portions, s.max_repeats) == (None, None, None)


# --- ranking and reserves ------------------------------------------------------------------------


def pool(slot: Slot, profile: Profile = OPEN) -> list[Recipe]:
    return [
        r
        for r in CATALOG.recipes.values()
        if slot in r.meal_types and allowed(r, CATALOG.foods, profile)
    ]


def protein_ratio(r: Recipe) -> Fraction:
    return Fraction(r.per_portion.protein_g, max(r.per_portion.kcal, 1))


def cost_ratio(r: Recipe) -> Fraction:
    cost = sum(i.grams * CATALOG.foods[i.food_id].price_per_kg for i in r.ingredients)
    return Fraction(cost, max(r.per_portion.kcal, 1))


@pytest.mark.parametrize("k", [1, 7, 16, 40, 1000])
def test_k_candidates_per_slot(k: int) -> None:
    specs, _ = select(CATALOG, OPEN, NO_PREFS, (), FOUR_SLOTS, k=k)
    for spec in specs:
        assert len(spec.candidates) == min(k, len(pool(spec.slot)))


def test_protein_and_price_reserves_come_first() -> None:
    targets = Targets(daily={}, weekly={Nutrient.PROTEIN: Band(500, None)})
    specs, recipes = select(CATALOG, OPEN, NO_PREFS, (), FOUR_SLOTS, targets=targets, budget=1)
    for spec in specs:
        everything = pool(spec.slot)
        protein = [recipes[rid] for rid in spec.candidates[:10]]  # ceil(40 / 4)
        rest = [r for r in everything if r.id not in spec.candidates[:10]]
        assert min(map(protein_ratio, protein)) >= max(map(protein_ratio, rest))
        cheap = [recipes[rid] for rid in spec.candidates[10:15]]  # ceil(40 / 8)
        rest = [r for r in rest if r.id not in spec.candidates[10:15]]
        assert max(map(cost_ratio, cheap)) <= min(map(cost_ratio, rest))


def test_no_reserves_without_a_protein_minimum_or_budget() -> None:
    plain = select(CATALOG, OPEN, NO_PREFS, (), FOUR_SLOTS, seed=3)
    capped = Targets(daily={Nutrient.PROTEIN: Band(None, 200), Nutrient.KCAL: Band(1800, 2000)})
    assert select(CATALOG, OPEN, NO_PREFS, (), FOUR_SLOTS, targets=capped, seed=3) == plain
    with_min = Targets(daily={Nutrient.PROTEIN: Band(80, None)})
    assert select(CATALOG, OPEN, NO_PREFS, (), FOUR_SLOTS, targets=with_min, seed=3) != plain


def test_small_k_never_overfills() -> None:
    targets = Targets(daily={Nutrient.PROTEIN: Band(80, None)})
    for k in (0, 1, 2):
        specs, _ = select(CATALOG, OPEN, NO_PREFS, (), FOUR_SLOTS, targets=targets, budget=5, k=k)
        assert all(len(s.candidates) == k for s in specs)


def test_rank_follows_preference() -> None:
    prefs = TastePrefs(liked_cuisines=frozenset({"Italian"}), disliked_cuisines=frozenset({"Thai"}))
    specs, recipes = select(CATALOG, OPEN, prefs, (), [(D, True)], k=1000)
    ranked = [recipes[rid].preference for rid in specs[0].candidates]
    assert ranked[: ranked.count(40)] == [40] * ranked.count(40)  # cuisine cap is k // 4 = 250
    assert ranked[-1] == min(ranked)


def test_cuisine_cap_then_top_up() -> None:
    thai = [rec(i, (1, 10), cuisine="Thai") for i in range(1, 21)]
    greek = [rec(i, (1, 10), cuisine="Greek") for i in range(21, 41)]
    other = [rec(i, (1, 10)) for i in range(41, 61)]
    prefs = TastePrefs(liked_cuisines=frozenset({"Thai"}))
    specs, recipes = select(catalog(thai + greek + other), OPEN, prefs, (), [(L, True)], k=8)
    cuisines = Counter(recipes[rid].cuisine for rid in specs[0].candidates)
    assert cuisines["Thai"] == 2  # k // 4, despite being liked
    assert cuisines["Greek"] <= 2
    assert sum(cuisines.values()) == 8
    specs, recipes = select(catalog(thai), OPEN, prefs, (), [(L, True)], k=8)
    assert len(specs[0].candidates) == 8  # nothing else to pick: pass 2 tops up
    # Below k = 4 the cap is 0: recipes with a cuisine wait for the top-up.
    specs, _ = select(catalog(thai + other[:1]), OPEN, prefs, (), [(L, True)], k=2)
    assert specs[0].candidates[0] == 41


def test_deterministic_per_seed() -> None:
    a = select(CATALOG, OPEN, NO_PREFS, (), FOUR_SLOTS, seed=7)
    assert select(CATALOG, OPEN, NO_PREFS, (), FOUR_SLOTS, seed=7) == a
    b = select(CATALOG, OPEN, NO_PREFS, (), FOUR_SLOTS, seed=8)
    assert [s.candidates for s in a[0]] != [s.candidates for s in b[0]]


@pytest.mark.parametrize("seed", range(10))
def test_novelty_penalty(seed: int) -> None:
    cat = catalog([rec(1, (1, 10)), rec(2, (1, 10))])
    for fresh, stale in ((1, 2), (2, 1)):
        specs, _ = select(
            cat, OPEN, NO_PREFS, (), [(L, True)], novelty=frozenset({stale}), k=1, seed=seed
        )
        assert specs[0].candidates == (fresh,)


def test_pantry_bonus_ranks_without_changing_preference() -> None:
    cat = catalog([rec(1, (4, 100)), rec(2, (1, 40), (3, 30), (5, 30))])
    prefs = TastePrefs(liked_food_ids=frozenset({1, 3, 5}))  # recipe 2: +45 > full pantry cover
    specs, recipes = select(cat, OPEN, prefs, [Lot(4, 500)], [(L, True)], k=1)
    assert specs[0].candidates == (2,)
    prefs = TastePrefs(liked_food_ids=frozenset({1}))  # recipe 2: +15 < full pantry cover (30)
    specs, recipes = select(cat, OPEN, prefs, [Lot(4, 500)], [(L, True)], k=1)
    assert specs[0].candidates == (1,)
    assert recipes[1].preference == 0
    # An expired lot doesn't count.
    specs, _ = select(cat, OPEN, prefs, [Lot(4, 500, expires=-1)], [(L, True)], k=1)
    assert specs[0].candidates == (2,)


def test_lots_expiring_soon_count_double() -> None:
    cat = catalog([rec(1, (4, 30), (5, 60)), rec(2, (1, 50))])
    prefs = TastePrefs(liked_food_ids=frozenset({1}))  # recipe 2: +15
    # A third of recipe 1 is in the pantry: 10 points, or 20 when the lot expires within 3 days
    # (by day index 2).
    soon = select(cat, OPEN, prefs, [Lot(4, 500, expires=2)], [(L, True)], k=1)
    assert soon[0][0].candidates == (1,)
    later = select(cat, OPEN, prefs, [Lot(4, 500, expires=3)], [(L, True)], k=1)
    assert later[0][0].candidates == (2,)


def test_only_grams_in_soon_lots_count_double() -> None:
    # Recipe 1 is 30 g of food 4 and 60 g of food 1 per portion; recipe 2 has a liked food (+15).
    cat = catalog([rec(1, (4, 30), (1, 60)), rec(2, (3, 50))])
    prefs = TastePrefs(liked_food_ids=frozenset({3}))

    def first(pantry: list[Lot]) -> int:
        specs, _ = select(cat, OPEN, prefs, pantry, [(L, True)], k=1)
        return specs[0].candidates[0]

    # 10 g expiring soon (x2) + 20 g from a later lot = 40 of 90 g: 13 points, below 15.
    assert first([Lot(4, 10, expires=1), Lot(4, 500)]) == 2
    # 30 g expiring soon (x2) = 60 of 90 g: 20 points.
    assert first([Lot(4, 30, expires=1), Lot(4, 500)]) == 1
    # Two lines of one food share its stock: 30 g in the pantry covers 30 of 90 g, 10 points.
    cat = catalog([rec(1, (4, 30), (4, 30), (1, 30)), rec(2, (3, 50))])
    specs, _ = select(cat, OPEN, prefs, [Lot(4, 30)], [(L, True)], k=1)
    assert specs[0].candidates == (2,)


def test_cuisine_cap_ignores_case() -> None:
    mixed = [rec(i, (1, 10), cuisine="Thai" if i % 2 else "thai") for i in range(1, 21)]
    other = [rec(i, (1, 10)) for i in range(21, 41)]
    prefs = TastePrefs(liked_cuisines=frozenset({"THAI"}))
    specs, recipes = select(catalog(mixed + other), OPEN, prefs, (), [(L, True)], k=8)
    assert sum(recipes[rid].cuisine is not None for rid in specs[0].candidates) == 2
