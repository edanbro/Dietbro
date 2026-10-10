# ADR-0014: Chat replans plan the open horizon; facts vs wishes; two contract additions

- Status: Accepted
- Date: 2026-10-10

## Context

M4 applies chat changes to the plan now ("simple replan"); M5 adds latency, warm starts and the
diff view. A design review of the first executor spec found that re-planning the whole week
with the past locked fails in ordinary use: locked past meals are re-judged against a profile
that changed mid-week (a new allergy makes every replan infeasible), the kcal band and floor
are hard on days where the user already ate a 1,800 kcal pizza or skipped dinner, earlier skips
and logs were forgotten by the next message, and each craving tried up to five planner runs.

## Decision

- **Open horizon.** A replan's problem starts today (or the plan's start, if later) and runs to
  the plan's end. Past days, and today's meals whose time has passed (from the client's local
  time), are copied into the new version unchanged and never re-validated; eaten-today meals
  count as `extra` intake. This is ADR-0009's "eaten marker" for M4.
- **Facts vs wishes.** Off-plan food and skips are facts: always logged (`meal_logs`), rebuilt
  into every later replan (empty slot + counted intake) until superseded. Cravings and swaps are
  wishes: they may fail with a reason, and the plan stays as it was for them.
- **Two additions to the planning contract (ADR-0009)**, so the facts and wishes fit in one
  planner run each:
  - `Problem.day_kcal`: a per-day kcal band replacing the daily band and the calorie floor on
    days with reported intake, set to the closest band the free slots can still reach.
  - `Problem.choices`: "the meal at (day, slot) must be one of these recipes", with eligibility,
    portions and every hard filter still applied (validator code `CHOICE`). Cravings, swaps and
    pinned meals use it; `locked` is only used for empty slots.
  The validator, the greedy baseline and the diagnosis honour both; `solve()` must too (its spec
  tests include them).
- **The planner gets the previous plan** (`Planner(problem, previous)`), so the churn weight
  keeps unrelated meals, and a replan keeps the parent's seed.
- **At most three planner runs** per request: everything; without soft wishes; facts only.

## Consequences

- Allergy or goal changes mid-week never block logging or replanning; past days keep the plan
  they had.
- Repeat caps and weekly macro bands count only the remaining days in a replan.
- Eduard's `solve()` takes two more inputs; both are small (a per-day bound and a per-cell
  domain restriction) and covered by the spec tests.
