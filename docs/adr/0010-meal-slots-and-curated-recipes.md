# ADR-0010: Four meal slots, curated breakfasts and snacks, data-quality exclusions

- Status: Accepted
- Date: 2026-10-09

## Context

The planner needs to know which recipes can fill which meal. TheMealDB has categories but no
meal types. Only 18 of its breakfasts have complete nutrition, nearly all with eggs, milk or
wheat (two are vegan), so a week of breakfasts for an egg-allergic or vegan user is impossible.
Some recipes have broken nutrition: deep-frying oil is counted in full (1,439 kcal per serving
of fried chicken), or a jam is categorised as a main. Options:

1. Plan only lunch and dinner and take a fixed allowance for the rest of the day.
2. Plan breakfast, lunch, dinner and an optional snack from TheMealDB alone.
3. Plan four slots and add a small curated set of simple breakfasts and snacks.

## Decision

Option 3.

- Slots: breakfast, lunch and dinner are required; snack is optional and costs a little in the
  objective, so it has to earn its place. Category → slots (`larder_core.meals`): mains fill
  lunch and dinner, starters lunch, breakfasts breakfast, desserts and curated snacks snack,
  sides nothing.
- Each slot has its own portion range: breakfast 0.5–1.5 servings, lunch 0.5–2, dinner 1–2,
  snack 0.5–1. A global range produced lopsided days (double breakfast, half-portion dinner).
  Breakfasts and snacks may repeat up to 4 times a week; mains twice.
- About 30 curated breakfasts and 20 snacks (`larder_data/curated.toml`), built from USDA foods
  through curated aliases with explicit servings. They include protein-dense and allergen-free
  options. A test checks that every common allergy and diet combination has enough of them.
- Recipes with implausible nutrition (over 1,000 kcal per serving, or frying oil over 25% of the
  recipe's weight) are not planned. `recipe_overrides.csv` reclassifies recipes TheMealDB
  mislabels (jams, pickles, sauces → not planned; cakes → snack). The data report lists every
  exclusion.

## Consequences

- Planning works for restrictive profiles. The curated set is ours to maintain, and its servings
  are explicit rather than estimated.
- A few genuine recipes are excluded with the broken ones. Overrides can bring them back.
- Generated recipes (M4) will need a slot assignment too: the same category rules, or an
  explicit slot.
