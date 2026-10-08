# ADR-0008: Optional body stats; calorie targets validated against floor and deficit

- Status: Accepted
- Date: 2026-10-08

## Context

PLAN §8: a configurable calorie floor and maximum daily deficit, and refuse extreme targets. A
deficit is only meaningful relative to energy needs, which need body data (sex, age, height,
weight, activity). That is sensitive personal data. Options:

1. **Targets + floor only.** Users type kcal/macro bands; we enforce an absolute floor. Minimal
   data, but can't catch "1,300 kcal for someone who burns 2,800".
2. **Optional body stats.** If given, estimate TDEE (Mifflin-St Jeor x activity factor), suggest
   targets, and enforce the maximum deficit; otherwise behave like option 1.
3. **Required body stats.** Strongest checks; more friction and more sensitive data for everyone.

## Decision

Option 2, implemented as pure functions in `larder_core.energy`:

- Absolute floor: targets below the user's floor are refused, and the floor itself can't be set
  under 1000 kcal. Default floor 1200 kcal; default max deficit 1000 kcal/day (max 1500).
- With body stats: the daily minimum must be within the max deficit of estimated TDEE.
- Also refused: max > 6000 kcal, min > max, macro minimums whose energy exceeds the daily max.
- Suggestions (lose −450, maintain, gain +300 kcal around TDEE, ±100 band, protein 1.2 g/kg)
  are constructed to always pass validation (property-tested).
- Adults only (age ≥ 18). Birth year is stored, not age. Body stats can be deleted any time.
- The UI shows the API's reasons verbatim and a "not medical advice" note.

## Consequences

- Users who skip body stats get only the floor check; the planner (M3) will still never go below
  the floor.
- Validation lives in one pure module used by the API and later by the solver and evals.
- Mifflin-St Jeor is a population estimate (±10%); good enough to stop dangerous targets, not to
  prescribe. Revisit if users report systematic mismatch.
