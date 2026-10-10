"""The executor: typed changes -> a new plan version. The only code that changes a plan from chat.

`apply_changes(scope, changes, source)` never raises for planning outcomes: every change gets a
ChangeResult, facts are always recorded, and a plan version is saved whenever anything changed.

1. Read phase (one short session, then closed)
   - Inputs: planning.load_inputs; goal_problems(inputs) non-empty -> every change fails with
     "Please review your goals in your profile" (facts are still logged).
   - Target plan P = the latest plan if P.start <= every change date <= P.end (P may start in
     the future). Facts dated outside every plan: logged only (no version). Wishes dated outside
     P fail ("Monday isn't in your plan yet - make next week's plan first"). Only when no plan
     covers today and a wish is dated today..today+6 is a fresh plan made (POST /plans rules,
     start = today), with `fresh=True`. Changes dated before today: facts are logged (and shown on
     that past day); wishes fail ("past days can't be changed").
   - Missing slot: AteOffPlan today -> the latest slot whose time has passed (SLOT_START), else
     dinner; anything else -> dinner. The result's message says what was assumed.
   - Conflicts within the message, grouped by (date, slot): AteOffPlan beats Skip (the Skip is
     'unchanged', no eating-elsewhere macros); several AteOffPlan on one slot are all logged;
     a Craving/Swap on a slot that also has a fact in this message fails ("You said you're
     skipping Fri dinner"); of two wishes on one slot the first applies, later ones fail.
   - Idempotency: change_key = sha256 of the canonical change JSON; a (message_id, change_key)
     already in `cravings` returns its stored result with status 'unchanged'.
2. Estimates (no DB connection held): offplan.estimate for each AteOffPlan.
3. The replan problem covers the open horizon only: day 0 = max(today, P.start), days = to
   P.end. Offset o = (day 0 - P.start). Past days are never in the problem.
   - Rebuilt from the database every time (not from this message alone): every active meal_log
     (voided_at IS NULL) dated in the horizon adds its macros to `extra[day]` and, if slotted,
     locks that slot to None; this message's facts are added the same way (a new slotted log
     voids the earlier active log for that (date, slot); a wish on a slot with an active skip
     voids the skip; on a slot with an active off_plan log it fails).
   - Today's meals whose time has passed (local_time >= SLOT_END[slot]; without local_time,
     none unless a change today names a later slot) are frozen: their macros go to `extra[0]`
     and their slot is locked to None, so they are never re-judged against today's profile;
     their rows are copied unchanged into the new version.
   - Pins: the parent's PlanMeals with locked=True in the horizon become `choices` of one
     recipe, if still visible and `candidates.allowed` under the current profile (else dropped,
     with a note). Wishes: a Craving/Swap with recipe_id -> choices=(id,) after the recipe guard
     (handlers.guard_recipe: visible to the user, plannable, slot in its meal types, allowed);
     with dish/tags -> choices = top 5 safe search hits for that slot; a Swap with nothing ->
     choices = that slot's candidates minus the current recipe (and minus recipes already on
     that date). Locks are only ever None.
   - day_kcal for every day with fixed intake (extra > 0 or a None-lock): fixed = extra[d];
     [lo, hi] = the kcal the free slots can reach (min/max over their candidates and portion
     ranges); band = Band(min(max(kcal_min, floor), fixed + hi), max(kcal_max, fixed + lo)).
     The day's result says when it lands outside the normal band ("Tue ~2,600 kcal with the
     pizza, above your 2,200 max"). Untouched days keep the hard band and the floor.
   - make_problem with seed = P.stats.seed, novelty = {}, the user's private recipes merged,
     every recipe named in choices added with its foods; check_problem after adding everything.
   - previous = the parent's meals with day >= o, re-indexed to day - o (churn weight keeps
     unrelated meals).
4. Solve (planning.Planner takes (problem, previous); runs via scope.solve, in a worker thread
   behind the process-wide planning.plan_limiter, replan_time_limit_ms): at most 3 runs -
   (a) everything; if that has no valid plan: (b) without soft wishes; then (c) facts only.
   Wishes dropped this way fail with the reason (diagnose lines when available). If (c) fails
   too, no version is saved but facts are still logged ("I logged it but couldn't re-plan
   Tuesday: ...").
5. Write phase (one short transaction): `pg_advisory_xact_lock(user_id)` (POST /plans takes it
   too), re-read the latest plan; if it is no longer P, rebuild once from the new latest, else
   fail the wishes with "your plan changed while I was working". Save version
   next_version(P.start) with parent_id = P.id, start_date = P.start, days = P.days: rows for
   days < o and today's frozen meals copied verbatim from P; solver meals shifted by +o;
   locked=True only for pins and this message's applied wishes; shopping list for the horizon
   with `checked` copied from P for the same food when the new grams <= P's. PlanStats v2:
   day_totals (past days from P.stats), `logged` per day (MealLogOut snapshot of active logs in
   the plan's dates), the outcome (results + diff) for explain_plan_diff, score with previous
   (score['churn']). MealLogs (plan_id = new version, else P.id) and one cravings row per
   change, committed in the same transaction.
6. ReplanOutcome: results per change, SlotChange diff vs P for days >= today (recipe or portion
   changes; reason = the change that caused it, else 'rebalance' / 'resize'), logged, DayKcal for
   changed days, warnings = hard violations dated >= today (baseline only), notes.
"""

from collections.abc import Sequence
from datetime import time
from typing import Literal

from larder_api.chat.scope import ChatScope
from larder_core.meals import Slot
from larder_llm.outcome import ReplanOutcome
from larder_llm.schemas import Change

# When a meal of the day is over (the user's local time). Snack: after dinner.
SLOT_START: dict[Slot, time] = {
    Slot.BREAKFAST: time(5, 0),
    Slot.LUNCH: time(11, 30),
    Slot.SNACK: time(15, 0),
    Slot.DINNER: time(17, 30),
}
SLOT_END: dict[Slot, time] = {
    Slot.BREAKFAST: time(10, 30),
    Slot.LUNCH: time(14, 30),
    Slot.DINNER: time(20, 30),
    Slot.SNACK: time(20, 30),
}


async def apply_changes(
    scope: ChatScope, changes: Sequence[Change], *, source: Literal["chat", "offline"]
) -> ReplanOutcome:
    raise NotImplementedError
