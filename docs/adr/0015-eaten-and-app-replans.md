# ADR-0015: Meals marked eaten, replans from the plan screen, and the replan latency budget

- Status: Accepted
- Date: 2026-10-11

## Context

M5 ("real-time replan") asks for replans without the chat, eaten tracking that draws down the
pantry, and a measured latency (p95 < 1 s at the API) with churn reported. ADR-0014 already
gives the executor: typed changes, open-horizon replans, facts (meal logs) rebuilt every time,
`previous` passed to the planner with a churn weight. Open questions were where "eaten" lives,
how it interacts with replans and versions, how the pantry changes, and how a non-chat replan
is exposed.

Options for "eaten":

1. **A new plan version per mark.** Uniform with replans, but marking three meals a day makes
   three versions with nothing re-planned, churns the shopping list and makes undo a revert.
2. **Only a flag on the meal row.** Cheap, but replans would not know the intake is fixed, and
   a new version (or POST /plans) would forget it.
3. **A meal log (fact) plus the row's status in place.** The log is what replans count, exactly
   like off-plan food; the row's status is display state, edited in place like shopping ticks.

## Decision

- **Eaten = option 3.** `POST /plans/{id}/meals/eaten {date, slot, today}` (on or before
  `today`, latest version only, else 400/404/409) writes `meal_logs` kind `eaten`, source
  `app`, with the planned meal's macros and `recipe_id` (not an estimate), voids other active
  logs for that meal, and sets `plan_meals.status = eaten`. No new version: the day's totals
  don't change. Repeating it is a no-op. `DELETE ...?date&slot` voids the log and gives the
  pantry back. Both take the per-user plan lock.
- **Replans and eaten meals.** An eaten log is fixed intake with its slot kept empty, like any
  log; the eaten row is carried into the new version unchanged (status eaten) and counted once
  (through `extra`, not listed in `logged`), and left out of `previous`. A wish for an eaten
  meal fails; a fact reported for it (a skip, other food) voids the mark and gives its pantry
  food back. Because a mark makes no version, the executor's write phase compares the active
  logs as well as the latest plan id under the lock and rebuilds if either changed.
- **Pantry.** Per food, the planner's grams per portion (staples and unresolved lines: none) x
  the row's portions, from the user's items of that food whose quantity converts to grams
  (`larder_core`), soonest-expiring first, never below zero; the share of the item's own
  quantity goes with the grams. Approximate items are used like any other: the planner counts
  their grams as stock, so leaving them would plan from food already eaten. Emptied items stay
  at 0 so undo can refill them. What was taken is stored on the log (`pantry_taken`); undo adds
  exactly that back (after a unit change, in the item's current grams per unit); deleted items
  are not recreated (`remaining_quantity` null, a note).
- **Replans without chat.** `POST /plans/replan {changes, client_id, today, local_time?}` takes
  the same `larder_llm.schemas.Change` union and runs the same executor (source `app`) in a scope
  with no thread, message or models, so results, versions and diffs are identical to the chat's.
  It shares the chat's turn lock (409 busy) and is idempotent by `client_id` (stored on
  `cravings`; a resend is 409 duplicate, as in the chat). Solves queue behind the process-wide
  `plan_limiter`.
- **Latency and churn.** The response carries `Server-Timing: replan;dur=<ms>`, the log line
  has the time and the meals changed, and the version's `stats.total_ms` keeps it.
  `make bench-replan` reports p50/p95 and churn for `scenarios.replan` problems and for the
  executor against the seeded database. CP-SAT must warm-start from `previous` (`AddHint`,
  solver README section 7) and replans should run with a shorter limit than new plans.

Migration 0005: `meal_logs.recipe_id`, `meal_logs.pantry_taken`, `cravings.client_id`.

## Consequences

- Eaten state is two writes (log + row status) kept consistent under one lock; a version saved
  later re-derives the status from the log. History versions keep the status they had.
- A new plan for the same week (POST /plans) shows an earlier eaten meal as a logged entry, not
  a row (the planner keeps its slot empty).
- Greedy replans measure p95 ~0.3 s end to end on the seeded catalogue
  (`docs/replan-bench-greedy.md`). With CP-SAT the budget is the risk: three runs at 1.5 s
  would blow it, so `replan_time_limit_ms` should drop to ~600-800 ms once `solve()` exists,
  and the bench re-run.
- The web client renders a `logged` entry of kind `eaten` and meal status `eaten` (UI work
  follows separately).
