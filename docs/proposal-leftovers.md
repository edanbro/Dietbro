# Proposal: cook once, eat twice in the solver

For Eduard. This is a proposal only: no code in `larder_solver` has changed.

## What ships now (no solver change)

The plan screen has a "Cook extra for tomorrow's lunch" action on a dinner. It sends one
`Swap(recipe_id=<tonight's recipe>)` for tomorrow's lunch through the existing replan executor.
The meal cards then say "Cook extra: it's tomorrow's lunch too" and "Leftovers from last night's
dinner" (worked out in the web app: same recipe at dinner on day *d* and lunch on day *d+1*).

That is already right for the numbers:

- **Shopping:** both meals' portions are counted, which is what cooking double needs.
- **Pantry:** marking each meal eaten draws its own portions, so the total equals cooking double.
- **Nutrition:** each meal keeps its own kcal and macros.

What it doesn't do:

- The planner never suggests leftovers by itself.
- The swap uses up one of the recipe's repeats (`Problem.max_repeats`, default 2). If the dish
  already appears twice that week, the swap fails with the usual repeat message.
- Leftovers are charged the full `Weights.repeat` penalty (£1.50) as if they were a third
  cooking of the dish, so later replans may undo them.

## Proposed solver support

1. **Data (prefilter, my side if you agree):** mark recipes that keep and reheat well. This could
   be a `keeps: bool` on `larder_solver.Recipe`, from categories (stews, curries, soups, bakes,
   chilli, pasta bakes) plus a curated list. Salads, eggs, fried fish and anything marked "serve
   immediately" would be excluded.
2. **Model:** for each day *d* and each recipe *r* with `keeps`, a Boolean
   `left[d, r] = x[d, dinner, r] AND x[d+1, lunch, r]`. Linearise it the standard way:
   `left <= x_dinner`, `left <= x_lunch`, `left >= x_dinner + x_lunch - 1`.
3. **Objective:**
   - Don't charge the repeat penalty for a lunch that is leftovers: subtract
     `Weights.repeat * left[d, r]`.
   - Add a small reward per leftover (less cooking), say `Weights.leftover = 50_000` (£0.50),
     tunable, and 0 when the user turns leftovers off.
4. **Repeat cap:** count a dinner-plus-leftover pair as one use of the recipe, so the cap is
   `sum_slots x - sum_d left[d, r] <= cap`.
5. **Preference:** a profile flag `leftovers: off | sometimes | often` scales the reward, so
   people who hate leftovers never get them.
6. **Locks:** a user's manual "cook extra" swap should lock the lunch (`locked=True`), as chat
   swaps do, so replans keep it.

## Data the prefilter can provide

- `keeps` per recipe (point 1).
- For each dinner candidate, whether the same recipe is also eligible for lunch (`slots` already
  says so), so the solver only builds `left` variables where they're possible. That's small: at
  most about 7 × the number of dinner candidates.

## Tests I'd add alongside

- With a strong leftover reward and a `keeps` recipe, the solver pairs dinner with the next
  day's lunch, and the pair counts once against `max_repeats`.
- With the preference off, results match today's.
- Allergy and diet safety are unchanged (leftovers are the same recipe, so nothing new).
