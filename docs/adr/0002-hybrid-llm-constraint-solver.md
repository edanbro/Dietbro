# ADR-0002: Hybrid planner — LLM for language, CP-SAT for the plan

- Status: Accepted
- Date: 2026-10-08

## Context

A meal plan has hard requirements: never include an allergen, keep daily kcal inside a band and
above a floor, don't use more of an ingredient than is in the pantry or on the shopping list, and
keep already-eaten meals fixed. It also has soft goals: preferences, pantry use, cost, waste,
variety, and — when re-planning — changing as little as possible.

Options:

1. **LLM-only.** Prompt a model with the pantry, goals and constraints; ask for a plan. Simple, but
   constraint satisfaction is probabilistic: it can't promise zero allergen violations, it is weak
   at arithmetic over a week of macros, and it can't minimise churn against a previous plan.
2. **Pure optimisation, no LLM.** Guarantees constraints, but can't understand "want something
   spicy tonight" or "had a Big Mac", and can't explain changes in plain language.
3. **Hybrid.** The LLM handles language (parse cravings / off-plan meals into structured
   constraints, rank or draft recipes, explain plan diffs). A constraint solver (OR-Tools CP-SAT)
   builds every plan. An independent validator checks every plan.

## Decision

Option 3. The LLM never outputs a plan directly. CP-SAT owns plan construction, including replans
(fixed past/locked slots, craving as hard lock or soft bonus, churn penalty, warm start from the
previous plan). A separate validator — never the solver grading itself — checks constraints at
runtime, in tests and in evals.

## Consequences

- Constraint guarantees are structural, so "zero allergen violations" is testable, not hoped for.
- More moving parts: a solver model to design and keep fast (candidate prefiltering, short time
  limits on replan), and LLM output must be schema-validated before it becomes solver input.
- The evals compare hybrid vs an LLM-only baseline, scored by the same validator; that comparison
  is the project's headline metric.
