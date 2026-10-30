# ADR-0020: Snacks through the day, by choice

- Status: Accepted
- Date: 2026-10-30

## Context

There was one optional snack slot, planned only "when it helps": it cost £1.20 in the objective,
so the planner rarely used it, and no real plan in our audit had one. People do snack. Across
national surveys snacks are about a fifth of the day's energy, at one or two a day
(`docs/research/normal-meals.md`), and how many a person wants varies a lot.

Options:

1. **A count**, "snacks a day: 0-3", with the planner placing them. It's a single control, but
   a count can't say "I always have something at 4 and never in the morning", and it needs a rule
   for what each snack is called on the plan.
2. **Named slots**, each with the choice a meal already has: plan it, I'll sort it, skip it.

## Decision

Option 2: morning, afternoon and evening snack slots.

- **`Slot.SNACK` stays as the afternoon one**, so existing plans, logs and templates still read
  correctly. `morning_snack` and `evening_snack` are new, and `Slot` is now in true eating order,
  with the afternoon snack before dinner.
- **A planned snack comes every day.** The slot is required, not priced: the user asked for it.
  `day_bands` already widens a day that has too little room left, so a replan can't be cornered
  by one. If allergies leave no snack candidates at all, the slot goes back to optional instead
  of refusing the week.
- **Defaults:** an afternoon snack, nothing in the morning or evening. So `meal_modes` stores
  differences from `default_mode`, not from "plan".
- **Snacks are "own" too.** "I'll sort it" keeps `SNACK_SHARE` (10%) of the day free for a piece
  of fruit from your bag.
- **Each snack is a whole serving.** Half an apple with peanut butter isn't what anyone has.
- **Meals shrink to make room.** Each snack takes `SNACK_SHARE` off the day before the meal sizes
  of ADR-0019 are worked out.
- **Not the same snack twice in a day, when there's choice.** With at least
  `MIN_SNACKS_PER_SLOT` (8) candidates per slot, they are dealt between the planned snacks by size
  (`_deal_snacks`), so popcorn can't turn up three times and every slot has a light option. That
  took no new solver constraint: disjoint candidates can't clash. With fewer they share and the
  repeat cap grows with the snacks: a vegan on 1,200-1,400 kcal with three snacks a day needs the
  light ones again and again, and a repeat is the lesser evil. One safe snack had daily likewise
  beats refusing the week.
- **Unnamed food still goes to a meal everyone has.** Logged food with no meal never lands in an
  opt-in slot (`UNNAMED_FOOD_SLOTS`).

## Consequences

- Existing users get a daily afternoon snack on their next plan, with slightly smaller meals. That
  matches what most people eat, and one tap in settings turns it off.
- A week with three snacks a day has 21 more meal choices: on the ten bench profiles it stays
  within the time limit, and every plan passes the validator.
- `Slot` values reach the database, the calendar, the plan page and the API client, so a new slot
  touches them all. We don't expect a fourth snack.
