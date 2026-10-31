# ADR-0019: Plan the meals people normally eat

- Status: Accepted
- Date: 2026-10-30

## Context

A user's lunch was Paracuca, a plate of roasted peanuts. TheMealDB files it as a starter, and
starters fill lunch (ADR-0010). That was the visible end of three problems:

1. **Category is not role.** TheMealDB's categories say what a dish contains, not whether it
   makes a meal: sides, tapas, condiments and bar snacks sat under mains and vegetarian.
2. **Nothing favoured normal meals.** Candidates came from a seeded hash over about 500 recipes,
   and protein and budget reserves. Most of the catalogue is regional cooking most users have
   never heard of, and only 21 curated mains were familiar for certain. A week of Seswaa and
   Mulukhiyah is valid and strange.
3. **Nothing balanced the day.** Only the daily total was constrained, so a 218 kcal lunch sat
   next to a 1,428 kcal dinner of two servings of dumplings.

`docs/research/normal-meals.md` has what people eat, with sources.

## Options

- **Ask the LLM to judge each plan.** It costs money per plan, adds latency and breaks the rule
  that the plan comes from the solver (ADR-0002).
- **Hard filter the catalogue to a whitelist.** Simple, but it takes the world's food away from
  people who want it, and allergies or a vegan diet could leave too little to plan a week.
- **Tag what's everyday per slot, and let the user choose how far to stray.** Chosen.

## Decision

- **More everyday meals.** About 90 curated recipes from the research: cereal and toast;
  sandwiches, wraps, jacket potatoes, soups and salads in a new `Light meal` category (lunch
  only); the commonest dinners with their starch in the recipe, so a curry comes with its rice.
- **A meal must be big enough.** A catalogue recipe under 250 kcal or 10 g protein a serving
  fills no main meal; under 200 kcal no breakfast; over 350 kcal no snack (that's a slice of a
  twelve-serving bake). `recipe_overrides.csv` handled the rest by hand and can bring back an
  exception. A user's own recipes are exempt: they know what they eat.
- **Everyday is per slot.** `everyday_recipes.csv` is a reviewed list of about 100 TheMealDB
  recipes and exceptions, slot by slot: bolognese is a dinner, a chicken soup is a lunch. A
  curated main counts as a dinner; a roast at lunch is for someone who chose it. It's a
  prefilter input only: `meal_types` still says what's eligible, so swaps and searches can reach
  everything.
- **`preferences.meal_style`**, on the Meals settings page. `everyday` (the default) keeps
  candidates to everyday recipes, favourites and liked cuisines. `mix` caps other recipes at half
  the candidates. `adventurous` is the old behaviour.
- **Top up, never fail.** With fewer than `MIN_EVERYDAY` (20) candidates, `everyday` tops up from
  other recipes, so a restrictive profile gets a plan: first recipes everyday in another slot (a
  chilli with rice is a fine lunch), then by rank. A top-up that's everyday nowhere is
  `SlotSpec.unusual` and each meal of it costs `Weights.unusual` (£2), more than a repeat (£1.50),
  so it comes only when nothing familiar fits the caps, the calories or the budget. Soft, for the
  reason the top-up exists: it must never turn into no plan.
- **Meals have a size.** `SlotSpec.kcal` is a soft band, a meal's share of the day ±35%; each kcal
  outside costs `Weights.balance` (1p). It goes straight on the choice variable, because a choice
  of recipe and portions fixes the meal's kcal, so the model gains no variables. Soft, because
  a hard rule could make a small eater's week infeasible. The greedy fallback doesn't search on
  it, only reports it through `metrics.score`.

## Consequences

- The default plan looks like a normal week, and the catalogue's range is one setting away.
- We maintain two reviewed lists. Recipes imported from TheMealDB in future aren't everyday until
  someone lists them, which is the safe side to fail on.
- The most restricted users (vegan and gluten-free together, say) can still see an unusual meal.
  More curated recipes fix that case by case; the alternative is failing to plan.
- A gluten-free loaf is one food standing in for many, tagged with egg, milk and soya because any of
  them may be in it. That keeps gluten-free bread from vegans and from dairy- or egg-free coeliacs,
  some of whom could eat a particular brand: wrong on the safe side, as an allergy app should be.
- 40% of a 2,000 kcal day is 800 kcal, and a 1,400 kcal dinner now costs about £2.80. Bigger eaters
  get bigger portions spread across meals rather than one huge dinner.
