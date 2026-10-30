"""The executor: typed changes -> a new plan version. The only code that changes a plan after it
is made (POST /plans/replan from the plan screen and the diary, ADR-0015).

`apply_changes(scope, changes)` never raises for planning outcomes: every change gets a
ChangeResult, facts are always recorded, and a plan version is saved whenever anything changed.

1. Read phase (one short session, then closed)
   - Inputs: planning.load_inputs; goal_problems(inputs) non-empty -> every change fails with
     "Please review your goals in your profile" (facts are still logged).
   - Target plan P = the plan in force on the anchor date (planning.plan_id_for: the newest
     version covering it, else the newest of all), the anchor being the earliest change date
     from today on (else today); so with next week's plan made, this week's changes still go
     to this week's plan. P is used if P.start <= every change date <= P.end (P may start in
     the future). Facts dated outside every plan: logged only (no version). Wishes dated outside
     P fail ("Monday isn't in your plan yet - make next week's plan first"). Only when no plan
     covers today and a wish is dated today..today+6 is a fresh plan made (POST /plans rules,
     start = today), with `fresh=True`. Changes dated before today: facts are logged (and shown on
     that past day - except beside a fresh week, which has no parent to copy: then only logged,
     against the plan that covers them); wishes fail ("past days can't be changed").
   - Missing slot: AteOffPlan today -> the latest slot whose time has passed (SLOT_START), else
     dinner; anything else -> dinner. The result's message says what was assumed.
   - Conflicts within the request, grouped by (date, slot): AteOffPlan beats Skip (the Skip is
     'unchanged', no eating-elsewhere macros); several AteOffPlan on one slot are all logged;
     a Craving/Swap on a slot that also has a fact in this request fails ("You said you're
     skipping Fri dinner"); of two wishes on one slot the first applies, later ones fail.
   - Idempotency: change_key = sha256 of the canonical change JSON; a (user, client_id,
     change_key) already in `cravings` returns its stored result with status 'unchanged'.
2. Estimates (no DB connection held): offplan.estimate for each AteOffPlan.
3. The replan problem covers the open horizon only: day 0 = max(today, P.start), days = to
   P.end. Offset o = (day 0 - P.start). Past days are never in the problem.
   - Rebuilt from the database every time (not from this request alone): every active meal_log
     (voided_at IS NULL) dated in the horizon adds its macros to `extra[day]` and, if slotted,
     locks that slot to None; this request's facts are added the same way (a new slotted log
     voids the earlier active log for that (date, slot); a wish on a slot with an active skip
     voids the skip; on a slot with an active off_plan or eaten log it fails). A meal marked
     eaten (kind "eaten", larder_api.eaten) is such a log: fixed intake, slot kept empty.
   - Today's meals whose time has passed (local_time >= SLOT_END[slot]; without local_time,
     none unless a change today names a later slot) are frozen: their macros go to `extra[0]`
     and their slot is locked to None, so they are never re-judged against today's profile;
     their rows are copied unchanged into the new version.
   - Pins: the parent's PlanMeals with locked=True in the horizon become `choices` of one
     recipe, if still visible and `candidates.allowed` under the current profile (else dropped,
     with a note); a wish on a pinned meal replaces the pin in the runs that keep the wish.
     Wishes: a Craving/Swap with recipe_id -> choices=(id,) after the recipe guard
     (search.guard_recipe: visible to the user, plannable, slot in its meal types, allowed);
     with dish/tags -> choices = top 5 safe search hits for that slot; a Swap with nothing ->
     choices = that slot's candidates minus the current recipe (and minus recipes already on
     that date). Locks are only ever None.
   - day_kcal for every day with fixed intake (extra > 0 or a None-lock): fixed = extra[d];
     [lo, hi] = the kcal the free slots can reach (min/max over their slot's candidates - never
     a wish's or pin's choices, which must fit the band, not set it - and portion ranges);
     band = Band(min(max(kcal_min, floor), fixed + hi), max(kcal_max, fixed + lo)).
     The day's result says when it lands outside the normal band ("Tue ~2,600 kcal with the
     pizza, above your 2,200 max"). Untouched days keep the hard band and the floor.
   - make_problem with seed = P.stats.seed, novelty = {}, the user's private recipes merged,
     every recipe named in choices added with its foods; check_problem after adding everything.
   - previous = the parent's meals with day >= o, re-indexed to day - o (churn weight keeps
     unrelated meals), minus today's frozen meals and meals marked eaten (kept as they were).
4. Solve (planning.Planner takes (problem, previous); runs via scope.solve, in a worker thread
   behind the process-wide planning.plan_limiter, replan_time_limit_ms): at most 3 runs -
   (a) everything; if that has no valid plan: (b) without soft wishes; then (c) facts only.
   Wishes dropped this way fail with the reason (diagnose lines when available). If (c) fails
   too, no version is saved but facts are still logged ("I logged it but couldn't re-plan
   Tuesday: ...").
5. Write phase (one short transaction): `pg_advisory_xact_lock(user_id)` (POST /plans and
   marking eaten take it too), re-read the latest plan and the active logs; if the plan is no
   longer P or the logs changed (a meal marked eaten or undone meanwhile), rebuild once from
   the new state, else fail the wishes with "your plan changed while I was working". Save
   version next_version(P.start) with parent_id = P.id, start_date = P.start, days = P.days:
   rows for days < o and today's frozen meals copied verbatim from P; solver meals shifted by +o;
   rows of cells with an active slotted log are never copied (the log replaces them), except
   a meal marked eaten that P still plans (same recipe): that row is copied (status eaten) and
   its log is counted once, through `extra`, not listed in `logged`; an eaten log this request
   voids (a skip or off-plan food reported for that meal) gives its pantry food back;
   locked=True only for pins and this request's applied wishes; shopping list for the horizon
   with `checked` copied from P (re-read under the lock, so ticks made meanwhile count) for
   the same food when the new grams <= P's. PlanStats v2:
   day_totals (past days from P.stats), `logged` per day (MealLogOut snapshot of active logs in
   the plan's dates), the outcome (results + diff) for "what changed", score with previous
   (score['churn']), total_ms = the executor's wall time. MealLogs (plan_id = new version,
   else P.id) and one cravings row per change, committed in the same transaction.
6. ReplanOutcome: results per change, SlotChange diff vs P for days >= today (recipe or portion
   changes; reason = the change that caused it, else 'rebalance' / 'resize'), logged, DayKcal for
   changed days, warnings = hard violations dated >= today (baseline only), notes.
"""

import hashlib
import json
import logging
import time as clock
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from larder_api import eaten, planning
from larder_api.changes import offplan, search
from larder_api.changes.scope import ChangeScope
from larder_api.schemas import MacrosOut
from larder_core.meals import SLOT_ORDER, SNACK_SLOTS, Slot
from larder_db import models as db
from larder_llm.outcome import (
    ChangeReason,
    ChangeResult,
    ChangeStatus,
    DayKcal,
    Logged,
    ReplanOutcome,
    SlotChange,
)
from larder_llm.schemas import AteOffPlan, Change, Craving, Skip, Swap
from larder_solver import (
    Macros,
    Meal,
    Nutrient,
    Plan,
    PlanResult,
    Problem,
    Violation,
    diagnose,
    hard,
)

logger = logging.getLogger(__name__)

# When a meal of the day is over (the user's local time).
SLOT_START: dict[Slot, time] = {
    Slot.BREAKFAST: time(5, 0),
    Slot.MORNING_SNACK: time(10, 30),
    Slot.LUNCH: time(11, 30),
    Slot.SNACK: time(15, 0),
    Slot.DINNER: time(17, 30),
    Slot.EVENING_SNACK: time(20, 30),
}
SLOT_END: dict[Slot, time] = {
    Slot.BREAKFAST: time(10, 30),
    Slot.MORNING_SNACK: time(11, 30),
    Slot.LUNCH: time(14, 30),
    Slot.SNACK: time(20, 30),
    Slot.DINNER: time(20, 30),
    Slot.EVENING_SNACK: time(23, 59),
}
# Food logged without a meal goes to one everyone has: the morning and evening snacks are opt-in.
UNNAMED_FOOD_SLOTS = (Slot.BREAKFAST, Slot.LUNCH, Slot.SNACK, Slot.DINNER)

MAX_HITS = 5  # recipes a craving or swap by words may become
REVIEW_GOALS = "Please review your goals in your profile before I change your plan."
CHANGED = "Your plan changed while I was working - please try again."

type DateSlot = tuple[date, Slot]  # a meal of the user's calendar
type Where = Literal["plan", "past", "outside", "fresh"]


def change_key(change: Change) -> str:
    """sha256 of the canonical change JSON: the same change twice in one request is one."""
    canonical = json.dumps(change.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def missing_slot(change: Change, today: date, local_time: time | None) -> Slot:
    """Food eaten today without a meal: the latest meal that has begun; anything else: dinner."""
    if isinstance(change, AteOffPlan) and change.when.date == today and local_time is not None:
        begun = [s for s in UNNAMED_FOOD_SLOTS if local_time >= SLOT_START[s]]
        if begun:
            return max(begun, key=lambda s: SLOT_START[s])
    return Slot.DINNER


def day_label(on: date, today: date) -> str:
    return f"{on:%a}" if abs((on - today).days) <= 6 else f"{on:%a} {on.day} {on:%b}"


@dataclass(slots=True)
class _Item:
    """One requested change while it is being applied."""

    index: int
    change: Change
    key: str
    on: date
    slot: Slot
    assumed: bool  # the slot was filled in by missing_slot
    status: ChangeStatus | None = None
    message: str = ""
    recipe_id: int | None = None
    recipe_name: str | None = None
    where: Where | None = None
    stored: bool = True  # gets a cravings row (not a repeat of one already stored)
    estimate: offplan.Estimate | None = None
    macros: Macros = field(default_factory=Macros)
    choices: tuple[int, ...] = ()
    voids_skips: frozenset[int] = frozenset()  # earlier skips of this meal, void if it applies

    @property
    def cell(self) -> DateSlot:
        return (self.on, self.slot)

    @property
    def fact(self) -> bool:
        return isinstance(self.change, AteOffPlan | Skip)

    @property
    def soft(self) -> bool:
        return isinstance(self.change, Craving) and self.change.strength == "soft"

    @property
    def pending(self) -> bool:
        return self.status is None

    def finish(self, status: ChangeStatus, message: str) -> None:
        self.status = status
        self.message = message

    @property
    def logs(self) -> bool:
        """Whether applying it writes a meal log (facts, unless superseded in this request)."""
        return self.fact and self.status != "unchanged" and self.stored


@dataclass(frozen=True, slots=True)
class _Target:
    """The plan the changes apply to: the latest plan, or a fresh week from today."""

    plan: db.MealPlan | None  # None: a fresh week
    start: date
    days: int
    seed: int
    novelty: frozenset[int] = frozenset()

    @property
    def fresh(self) -> bool:
        return self.plan is None

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.days - 1)

    def covers(self, on: date) -> bool:
        return self.start <= on <= self.end

    def day(self, on: date) -> int:
        return (on - self.start).days

    def date(self, day: int) -> date:
        return self.start + timedelta(days=day)


@dataclass(slots=True)
class _Read:
    inputs: planning.UserInputs | None
    blocked: str | None  # why nothing can be planned (setup, goals)
    latest: db.MealPlan | None
    logs: list[db.MealLog]  # active logs around the plan's dates
    window: tuple[date, date]  # the dates `logs` were read for
    seen: dict[str, db.Craving]  # this request's stored changes, by key
    private: planning.PlanningCatalog
    fresh_version: int
    names: dict[int, str] = field(default_factory=dict[int, str])
    anchor: date | None = None  # the date P was chosen for (re-checked in the write phase)


@dataclass(slots=True)
class _Solved:
    problem: Problem
    result: PlanResult
    plan: Plan
    violations: list[Violation]
    previous: Plan | None
    applied: list[_Item]  # wishes in the plan
    pins: dict[DateSlot, int]  # pinned meals kept


@dataclass(slots=True)
class _Plan:
    """Everything decided before the write phase."""

    target: _Target | None
    offset: int  # first day of the target that is planned (or copied, without a horizon run)
    frozen: dict[Slot, db.PlanMeal | None]  # today's meals that are over (target day `offset`)
    solved: _Solved | None = None
    copy_only: bool = False  # a version that only carries the parent over (past-day logs)
    voided: set[int] = field(default_factory=set[int])  # earlier logs this request replaces
    notes: list[str] = field(default_factory=list[str])

    @property
    def saves(self) -> bool:
        return self.solved is not None or self.copy_only


async def apply_changes(
    scope: ChangeScope,
    changes: Sequence[Change],
    *,
    estimates: dict[int, offplan.Estimate] | None = None,
) -> ReplanOutcome:
    """`estimates` (by change index) are used as they are instead of estimating from names:
    the diary's quick-add knows the exact foods and grams."""
    estimates = dict(estimates or {})
    started = clock.perf_counter()
    for attempt in range(2):
        outcome = await _attempt(scope, changes, estimates, started, last=attempt == 1)
        if outcome is not None:
            return outcome
        logger.info("plan of user %s changed during a replan; rebuilding", scope.user_id)
    raise AssertionError("unreachable")  # the last attempt always returns


async def _attempt(
    scope: ChangeScope,
    changes: Sequence[Change],
    estimates: dict[int, offplan.Estimate],
    started: float,
    *,
    last: bool,
) -> ReplanOutcome | None:
    items = [
        _Item(
            index=i,
            change=c,
            key=change_key(c),
            on=c.when.date,
            slot=c.when.slot or missing_slot(c, scope.today, scope.local_time),
            assumed=c.when.slot is None,
        )
        for i, c in enumerate(changes)
    ]
    read = await _read(scope, items)
    _repeats(items, read)
    target = _target(scope, items, read)
    _conflicts(scope, items)
    if read.blocked is not None:
        logged = f"I logged it, but {read.blocked[0].lower()}{read.blocked[1:]}"
        for item in items:
            if item.pending:
                item.finish("failed", logged if item.fact else read.blocked)
    decided = await _decide(scope, items, read, target)
    await _estimates(scope, items, read, estimates)
    if decided.target is not None and read.inputs is not None and read.blocked is None:
        await _solve(scope, items, read, decided)
    return await _write(scope, items, read, decided, started, last=last)


# --- 1. read --------------------------------------------------------------------------------


async def _read(scope: ChangeScope, items: list[_Item]) -> _Read:
    async with scope.sessionmaker() as session:
        user = await session.get(db.User, scope.user_id)
        assert user is not None
        inputs: planning.UserInputs | None = None
        blocked: str | None = None
        try:
            inputs = await planning.load_inputs(session, user)
        except planning.SetupIncomplete as e:
            blocked = " ".join(e.missing)
        if inputs is not None and planning.goal_problems(inputs):
            blocked = REVIEW_GOALS
        anchor = min((i.on for i in items if i.on >= scope.today), default=scope.today)
        latest = await planning.plan_for(session, scope.user_id, anchor)
        dates = [i.on for i in items] + [scope.today, scope.today + timedelta(days=6)]
        if latest is not None:
            dates += [latest.start_date, latest.start_date + timedelta(days=latest.days - 1)]
        window = (min(dates), max(dates))
        logs = list(
            await session.scalars(
                select(db.MealLog)
                .where(
                    db.MealLog.user_id == scope.user_id,
                    db.MealLog.voided_at.is_(None),
                    db.MealLog.eaten_on.between(*window),
                )
                .order_by(db.MealLog.id)
            )
        )
        seen: dict[str, db.Craving] = {}
        if scope.client_id is not None:
            seen = {
                c.change_key: c
                for c in await session.scalars(
                    select(db.Craving).where(
                        db.Craving.user_id == scope.user_id,
                        db.Craving.client_id == scope.client_id,
                        db.Craving.change_key.in_([i.key for i in items]),
                    )
                )
            }
        private = await planning.load_private_recipes(session, scope.user_id)
        fresh_version = await planning.next_version(session, scope.user_id, scope.today)
        names = {
            r.id: r.name
            for r in await session.scalars(
                select(db.Recipe).where(
                    db.Recipe.id.in_({m.recipe_id for m in latest.meals} if latest else set())
                )
            )
        }
    return _Read(inputs, blocked, latest, logs, window, seen, private, fresh_version, names, anchor)


def _repeats(items: list[_Item], read: _Read) -> None:
    """The same change again in this request: its stored result, as 'unchanged'."""
    keys: set[str] = set()
    for item in items:
        stored = read.seen.get(item.key)
        if stored is not None:
            item.stored = False
            item.finish("unchanged", stored.message or "Already done.")
        elif item.key in keys:
            item.stored = False
            item.finish("unchanged", "Already done (you asked for this twice).")
        keys.add(item.key)


def _target(scope: ChangeScope, items: list[_Item], read: _Read) -> _Target | None:
    """Where each change lands: the latest plan, a past day of it, outside every plan (facts are
    logged only, wishes fail), or a fresh week when no plan covers today."""
    latest = read.latest
    plan = (
        _Target(
            latest,
            latest.start_date,
            latest.days,
            planning.PlanStats.model_validate(latest.stats).seed,
        )
        if latest is not None
        else None
    )
    ended = plan is None or plan.end < scope.today
    week = range(7)
    fresh = None
    if ended and any(not i.fact and i.pending and (i.on - scope.today).days in week for i in items):
        fresh = _Target(
            None,
            scope.today,
            planning.DAYS,
            planning.plan_seed(scope.user_id, scope.today, read.fresh_version),
            frozenset(m.recipe_id for m in latest.meals) if latest else frozenset[int](),
        )
    target = fresh or plan
    modes = planning.meal_modes(read.inputs.preferences if read.inputs else None)
    for item in items:
        if item.on < scope.today:
            item.where = "past" if plan is not None and plan.covers(item.on) else "outside"
        elif target is not None and target.covers(item.on):
            item.where = "fresh" if fresh is not None else "plan"
        else:
            item.where = "outside"
        if not item.pending or item.fact:
            continue
        if item.on < scope.today:
            item.finish("failed", "Past days can't be changed.")
        elif item.where == "outside":
            day = day_label(item.on, scope.today)
            item.finish("failed", f"{day} isn't in your plan yet - make that week's plan first.")
        elif modes[item.slot] != "plan":
            why = "you sort it out yourself" if modes[item.slot] == "own" else "you skip it"
            item.finish(
                "failed",
                f"{item.slot.capitalize()} isn't planned: {why}. You can change that in "
                "Profile, under Meals to plan.",
            )
    return target


def _conflicts(scope: ChangeScope, items: list[_Item]) -> None:
    """Within one request: off-plan food beats a skip of the same meal; a wish on a meal the
    request also reports fails; of two wishes on one meal, the first applies."""
    by_cell: dict[DateSlot, list[_Item]] = {}
    for item in items:
        if item.pending or (item.fact and item.status != "unchanged"):
            by_cell.setdefault(item.cell, []).append(item)
    for (on, slot), group in by_cell.items():
        when = f"{day_label(on, scope.today)} {slot}"
        ate = [i for i in group if isinstance(i.change, AteOffPlan)]
        skips = [i for i in group if isinstance(i.change, Skip)]
        if ate:
            for item in skips:
                if item.pending:
                    item.finish(
                        "unchanged", f"You told me what you had for {when}, so I logged that."
                    )
        facts = ate or skips
        wishes = [i for i in group if not i.fact and i.pending]
        for n, item in enumerate(wishes):
            if facts:
                said = "skipping" if not ate else "having something else for"
                item.finish("failed", f"You said you're {said} {when}, so I left it.")
            elif n > 0:
                item.finish("failed", f"You already asked for something else for {when}.")


# --- 2. decide what goes into the problem ---------------------------------------------------


def _frozen_slots(scope: ChangeScope, items: list[_Item]) -> set[Slot]:
    """Today's meals that are over: by the local time, or without it, those before the latest
    meal a change today names."""
    if scope.local_time is not None:
        return {s for s in Slot if scope.local_time >= SLOT_END[s]}
    named = [SLOT_END[i.slot] for i in items if i.on == scope.today and i.pending]
    if not named:
        return set()
    return {s for s in Slot if SLOT_END[s] < max(named)}


async def _decide(
    scope: ChangeScope, items: list[_Item], read: _Read, target: _Target | None
) -> _Plan:
    active: dict[DateSlot, list[db.MealLog]] = {}
    for log in read.logs:
        if log.slot is not None:
            active.setdefault((log.eaten_on, Slot(log.slot)), []).append(log)
    # A new log of a meal replaces what was logged for it before.
    voided = {log.id for i in items if i.logs for log in active.get(i.cell, [])}
    if target is None:
        return _Plan(None, 0, {}, voided=voided)
    day0 = max(scope.today, target.start)
    offset = target.day(day0)
    frozen: dict[Slot, db.PlanMeal | None] = {}
    if target.plan is not None and day0 == scope.today and target.covers(day0):
        rows = {m.slot: m for m in target.plan.meals if m.day == offset}
        frozen = {s: rows.get(s) for s in _frozen_slots(scope, items)}
    decided = _Plan(target, offset, frozen, voided=voided)
    for item in items:
        if item.fact or not item.pending:
            continue
        when = f"{day_label(item.on, scope.today)} {item.slot}"
        if item.on == scope.today and item.slot in frozen:
            item.finish("failed", f"{when} is already over.")
            continue
        earlier = active.get(item.cell, [])
        had = next((log for log in earlier if log.kind in ("off_plan", "eaten")), None)
        if had is not None:
            said = "logged" if had.kind == "off_plan" else "marked"
            what = had.description if had.kind == "off_plan" else f"{had.description} eaten"
            item.finish("failed", f"You already {said} {what} for {when}, so I left it.")
            continue
        item.voids_skips = frozenset(log.id for log in earlier)
        await _choose(scope, item, when)
    return decided


async def _choose(scope: ChangeScope, item: _Item, when: str) -> None:
    """A wish's recipes: an exact id (guarded), the top safe search hits for its words, or, for
    a swap without either, decided once the problem's candidates are known."""
    change = item.change
    assert isinstance(change, Craving | Swap)
    if change.recipe_id is not None:
        reason = await search.guard_recipe(scope, change.recipe_id, item.slot)
        if reason is not None:
            item.finish("failed", reason)
        else:
            item.choices = (change.recipe_id,)
        return
    words = " ".join([change.dish or "", *change.tags]).strip()
    if not words:
        if isinstance(change, Craving):
            item.finish("failed", f"Tell me what you'd like for {when}.")
        return  # a swap to anything else: see _swap_choices
    hits = await search.search_recipes(scope, words, item.slot, limit=MAX_HITS)
    if not hits:
        item.finish("failed", f"I couldn't find {words} that's safe for you and fits {item.slot}.")
        return
    item.choices = tuple(h.id for h in hits)


async def _estimates(
    scope: ChangeScope, items: list[_Item], read: _Read, cache: dict[int, offplan.Estimate]
) -> None:
    """What each fact adds to its day (no database connection held while estimating)."""
    rows = {}
    if read.latest is not None:
        start = read.latest.start_date
        rows = {(start + timedelta(days=m.day), Slot(m.slot)): m for m in read.latest.meals}
    for item in items:
        if not item.logs:
            continue
        change = item.change
        if isinstance(change, AteOffPlan):
            if item.index not in cache:
                resolved = change.model_copy(
                    update={"when": change.when.model_copy(update={"slot": item.slot})}
                )
                cache[item.index] = await offplan.estimate(scope, resolved)
            item.estimate = cache[item.index]
            item.macros = item.estimate.macros
        elif isinstance(change, Skip) and change.eating_elsewhere:
            planned = rows.get(item.cell)
            typical = offplan.TYPICAL_SNACK if item.slot in SNACK_SLOTS else offplan.TYPICAL_MAIN
            item.macros = (
                Macros(planned.kcal, planned.protein_g, planned.fat_g, planned.carbs_g)
                if planned is not None
                else typical
            )


# --- 3-4. the horizon problem and at most three planner runs --------------------------------


def _wished(items: Iterable[_Item]) -> list[_Item]:
    return [i for i in items if not i.fact and i.pending and i.where in ("plan", "fresh")]


async def _solve(scope: ChangeScope, items: list[_Item], read: _Read, decided: _Plan) -> None:
    target = decided.target
    inputs = read.inputs
    assert target is not None
    assert inputs is not None
    offset = decided.offset
    days = target.days - offset
    horizon = [
        i
        for i in items
        if (i.logs or i.pending) and i.where in ("plan", "fresh") and target.day(i.on) >= offset
    ]
    # Past-day facts get a copied version of the plan they fall in; a fresh week (no plan
    # covers today) has no parent to copy, so they are only logged (against the latest plan).
    past_facts = target.plan is not None and any(i.logs and i.where == "past" for i in items)
    if days <= 0 or not horizon:
        decided.copy_only = past_facts
        return

    day0 = target.date(offset)
    shared = await scope.catalog.get(scope.sessionmaker)
    pool = shared.merged(read.private)
    base = planning.make_problem(
        inputs,
        shared,
        day0,
        days=days,
        k=scope.settings.plan_candidates,
        seed=target.seed,
        novelty=target.novelty,
        private=read.private,
    )

    def pday(on: date) -> int:
        return (on - day0).days

    rows = (
        {(target.date(m.day), Slot(m.slot)): m for m in target.plan.meals}
        if target.plan is not None
        else {}
    )
    _swap_choices(items, base, rows)
    wishes = _wished(items)
    facts = [i for i in horizon if i.logs]
    if not wishes and not facts:
        decided.copy_only = past_facts
        return
    pins = await _pins(scope, items, read, decided, rows)

    modes = planning.meal_modes(read.inputs.preferences if read.inputs else None)
    unplanned = {slot for slot, mode in modes.items() if mode != "plan"}

    def build(chosen: list[_Item], keep_pins: bool) -> Problem:
        extra: dict[int, Macros] = {}
        empty: set[tuple[int, Slot]] = set()
        voided = decided.voided.union(*(i.voids_skips for i in chosen))
        for log in read.logs:
            if log.id in voided or not 0 <= pday(log.eaten_on) < days:
                continue
            d = pday(log.eaten_on)
            extra[d] = extra.get(d, Macros()) + Macros(
                log.kcal, log.protein_g, log.fat_g, log.carbs_g
            )
            if log.slot is not None:
                empty.add((d, Slot(log.slot)))
        for item in facts:
            d = pday(item.on)
            extra[d] = extra.get(d, Macros()) + item.macros
            empty.add((d, item.slot))
        for slot, row in decided.frozen.items():
            if (0, slot) in empty or (row is None and slot in unplanned):
                continue  # an own meal that's over keeps its share of the day (constrain)
            empty.add((0, slot))
            if row is not None:
                extra[0] = extra.get(0, Macros()) + Macros(
                    row.kcal, row.protein_g, row.fat_g, row.carbs_g
                )
        choices: dict[tuple[int, Slot], tuple[int, ...]] = {}
        if keep_pins:
            choices |= {(pday(on), slot): (rid,) for (on, slot), rid in pins.items()}
        choices |= {(pday(i.on), i.slot): i.choices for i in chosen}
        return planning.constrain(base, inputs, pool, choices=choices, empty=empty, extra=extra)

    # Meals kept as they were (over today, or marked eaten) aren't the planner's to change.
    eaten_cells = {
        (log.eaten_on, Slot(log.slot))
        for log in read.logs
        if log.kind == "eaten" and log.slot is not None and log.id not in decided.voided
    }
    previous = (
        planning.meals_plan(
            (
                m
                for m in target.plan.meals
                if not (m.day == offset and Slot(m.slot) in decided.frozen)
                and (target.date(m.day), Slot(m.slot)) not in eaten_cells
            ),
            offset,
        )
        if target.plan is not None
        else None
    )
    hard_wishes = [i for i in wishes if not i.soft]
    runs: list[tuple[list[_Item], bool]] = [(wishes, True)]
    if len(hard_wishes) < len(wishes):
        runs.append((hard_wishes, True))
    if facts and (hard_wishes or pins):
        runs.append(([], False))
    if not facts:
        runs = [(w, p) for w, p in runs if w]
    for n, (chosen, keep_pins) in enumerate(runs):
        problem = build(chosen, keep_pins)
        result = await scope.solve(problem, previous)
        try:
            plan, violations = planning.check_outcome(problem, result)
        except planning.PlanningError as e:
            why = _why(problem, e)
            later, later_pins = runs[n + 1] if n + 1 < len(runs) else ([], False)
            for item in chosen:
                if all(item.index != x.index for x in later):
                    item.finish(
                        "failed",
                        f"I couldn't fit {_wanted(item)} into {_when(item, scope.today)}: {why}",
                    )
            if keep_pins and pins and not later_pins:
                decided.notes.append(f"I couldn't keep your pinned meals: {why}")
            if n + 1 == len(runs):
                for item in facts:
                    day = day_label(item.on, scope.today)
                    item.finish("applied", f"I logged it but couldn't re-plan {day}: {why}")
            continue
        decided.solved = _Solved(
            problem, result, plan, violations, previous, chosen, pins if keep_pins else {}
        )
        return


def _wanted(item: _Item) -> str:
    change = item.change
    if isinstance(change, Craving | Swap):
        return change.dish or " ".join(change.tags) or "that"
    return "that"


def _why(problem: Problem, error: planning.PlanningError) -> str:
    if error.status_code == 503:
        return "planning took too long - please try again."
    lines = diagnose(problem)
    if error.status_code == 400 and lines:
        return lines[0]
    return "it didn't fit your calorie range for that day."


def _swap_choices(items: list[_Item], base: Problem, rows: dict[DateSlot, db.PlanMeal]) -> None:
    """A swap to anything else: the slot's candidates minus the current meal and the recipes
    already planned that day."""
    for item in _wished(items):
        if item.choices:
            continue
        spec = base.spec(item.slot)
        that_day = {m.recipe_id for (on, _), m in rows.items() if on == item.on}
        current = rows.get(item.cell)
        options = tuple(
            r
            for r in (spec.candidates if spec else ())
            if r not in that_day and (current is None or r != current.recipe_id)
        )
        if options:
            item.choices = options
        else:
            item.finish("failed", "I couldn't find anything else safe for that meal.")


async def _pins(
    scope: ChangeScope,
    items: list[_Item],
    read: _Read,
    decided: _Plan,
    rows: dict[DateSlot, db.PlanMeal],
) -> dict[DateSlot, int]:
    """Meals the user pinned earlier (locked) stay, if still safe and not reported eaten or
    skipped. A wish on a pinned meal overrides the pin only in the runs that keep the wish
    (build: its choices replace the pin's), so a soft wish that is dropped leaves the pin."""
    target = decided.target
    assert target is not None
    touched = {i.cell for i in items if i.logs and i.where in ("plan", "fresh")}
    logged = {(log.eaten_on, Slot(log.slot)) for log in read.logs if log.slot is not None}
    today_over = {(scope.today, s) for s in decided.frozen}
    pins: dict[DateSlot, int] = {}
    for (on, slot), meal in rows.items():
        cell = (on, slot)
        if (
            not meal.locked
            or target.day(on) < decided.offset
            or cell in touched | logged | today_over
        ):
            continue
        reason = await search.guard_recipe(scope, meal.recipe_id, slot)
        if reason is None:
            pins[cell] = meal.recipe_id
        else:
            when = f"{day_label(on, scope.today)} {slot}"
            decided.notes.append(f"I took your pinned meal off {when}: {reason}")
    return pins


# --- 5. write -------------------------------------------------------------------------------


async def _write(
    scope: ChangeScope,
    items: list[_Item],
    read: _Read,
    decided: _Plan,
    started: float,
    *,
    last: bool,
) -> ReplanOutcome | None:
    unshoppable = (await scope.catalog.get(scope.sessionmaker)).unshoppable
    unshoppable |= read.private.unshoppable
    async with scope.sessionmaker() as session:
        await planning.lock_user_plans(session, scope.user_id)
        # A meal marked eaten (or undone) meanwhile changes the plan without a new version.
        if decided.saves and (
            await _latest_id(session, scope.user_id, read.anchor or scope.today)
            != (read.latest.id if read.latest else None)
            or await _log_ids(session, scope.user_id, read.window) != {log.id for log in read.logs}
        ):
            if not last:
                await session.rollback()
                return None
            for item in items:
                if not item.fact and item.pending:
                    item.finish("failed", CHANGED)
            decided.solved, decided.copy_only = None, False
        _finish(scope, items, decided)
        voided = decided.voided.union(*(i.voids_skips for i in items if i.status == "applied"))
        new_logs = [_log(item, scope.user_id) for item in items if item.logs]
        row: db.MealPlan | None = None
        if decided.saves:
            row = await _save(scope, session, items, read, decided, voided, new_logs, unshoppable)
        outcome = _outcome(scope, items, read, decided, row, new_logs)
        if row is not None:
            stats = planning.PlanStats.model_validate(row.stats)
            stats.outcome = outcome
            stats.total_ms = round((clock.perf_counter() - started) * 1000)
            row.stats = stats.model_dump(mode="json")
        if voided:
            await session.execute(
                update(db.MealLog)
                .where(db.MealLog.id.in_(voided), db.MealLog.voided_at.is_(None))
                .values(voided_at=scope.now)
            )
            # A meal marked eaten that the user now reports otherwise: its pantry food back.
            await eaten.give_back_logs(
                session, scope.user_id, [log for log in read.logs if log.id in voided], read.latest
            )
        cravings: dict[int, db.Craving] = {}
        for item in items:
            if not item.stored:
                continue
            plan_id = row.id if row is not None else (read.latest.id if read.latest else None)
            cravings[item.index] = db.Craving(
                user_id=scope.user_id,
                intent=item.change.intent,
                parsed=item.change.model_dump(mode="json"),
                change_key=item.key,
                client_id=scope.client_id,
                status=item.status,
                message=item.message,
                plan_id=plan_id,
            )
        session.add_all(cravings.values())
        await session.flush()
        for item, log in zip([i for i in items if i.logs], new_logs, strict=True):
            log.craving_id = cravings[item.index].id
            log.plan_id = _log_plan(item, read, row)
        session.add_all(new_logs)
        await session.commit()
    return outcome


async def _log_ids(session: AsyncSession, user_id: int, window: tuple[date, date]) -> set[int]:
    """The user's active logs in `window` now (under the plan lock)."""
    return set(
        await session.scalars(
            select(db.MealLog.id).where(
                db.MealLog.user_id == user_id,
                db.MealLog.voided_at.is_(None),
                db.MealLog.eaten_on.between(*window),
            )
        )
    )


async def _latest_id(session: AsyncSession, user_id: int, anchor: date) -> int | None:
    return await planning.plan_id_for(session, user_id, anchor)


def _log_plan(item: _Item, read: _Read, row: db.MealPlan | None) -> int | None:
    """The version that shows the log: the new one, else the plan covering its date."""
    for plan in (row, read.latest):
        if plan is not None and 0 <= (item.on - plan.start_date).days < plan.days:
            return plan.id
    return None


def _when(item: _Item, today: date) -> str:
    return f"{day_label(item.on, today)} {item.slot}"


def _finish(scope: ChangeScope, items: list[_Item], decided: _Plan) -> None:
    """Final wording for every change still open: wishes in the saved plan, and facts."""
    solved = decided.solved
    for item in items:
        if not item.pending and not (item.fact and item.status == "failed"):
            continue
        when = _when(item, scope.today)
        if not item.fact:
            assert item.pending
            meal = _planned(decided, item) if solved and item in solved.applied else None
            if meal is None or solved is None:
                item.finish("failed", "I couldn't change that meal.")
                continue
            item.recipe_id = meal.recipe_id
            item.recipe_name = solved.problem.recipes[meal.recipe_id].name
            kept = _before(decided, item) == meal.recipe_id  # a swap to itself keeps the meal
            item.finish("applied", f"{when} {'stays' if kept else 'is now'} {item.recipe_name}.")
        elif item.pending:
            item.finish("applied", _fact_message(item, scope.today, decided.target))
        if item.assumed and item.status != "unchanged":
            item.message += f" I took that as {item.slot}."


def _before(decided: _Plan, item: _Item) -> int | None:
    """The recipe the item's meal had before this change."""
    target = decided.target
    if target is None or target.plan is None:
        return None
    day = target.day(item.on)
    return next(
        (m.recipe_id for m in target.plan.meals if m.day == day and Slot(m.slot) == item.slot),
        None,
    )


def _planned(decided: _Plan, item: _Item) -> Meal | None:
    solved, target = decided.solved, decided.target
    assert solved is not None
    assert target is not None
    return solved.plan.at(target.day(item.on) - decided.offset, item.slot)


def _fact_message(item: _Item, today: date, target: _Target | None) -> str:
    when = _when(item, today)
    change = item.change
    if isinstance(change, Skip):
        if change.eating_elsewhere:
            return f"Skipped {when}; I counted ~{item.macros.kcal:,} kcal for eating elsewhere."
        return f"Skipped {when}."
    assert isinstance(change, AteOffPlan)
    assert item.estimate is not None
    e = item.estimate
    text = f"Logged {change.description} for {when} (~{e.macros.kcal:,} kcal"
    text += ", an estimate)." if e.estimated else ")."
    if e.note:
        text += f" {e.note}"
    elif e.unmatched:
        text += f" I couldn't find {', '.join(e.unmatched)}, so it isn't counted."
    if item.where == "outside" or target is None or not target.covers(item.on):
        text += " It isn't in your plan, so nothing else changed."
    return text


def _log(item: _Item, user_id: int) -> db.MealLog:
    change = item.change
    m = item.macros
    if isinstance(change, AteOffPlan):
        assert item.estimate is not None
        kind, description = "off_plan", change.description
        estimated, found = item.estimate.estimated, item.estimate.items
    else:
        assert isinstance(change, Skip)
        kind = "skipped"
        description = "Eating elsewhere" if change.eating_elsewhere else "Skipped"
        estimated, found = change.eating_elsewhere, []
    return db.MealLog(
        user_id=user_id,
        eaten_on=item.on,
        slot=item.slot.value,
        kind=kind,
        description=description,
        kcal=m.kcal,
        protein_g=m.protein_g,
        fat_g=m.fat_g,
        carbs_g=m.carbs_g,
        estimated=estimated,
        items=found,
        source="app",
    )


async def _save(
    scope: ChangeScope,
    session: AsyncSession,
    items: list[_Item],
    read: _Read,
    decided: _Plan,
    voided: set[int],
    new_logs: list[db.MealLog],
    unshoppable: frozenset[int],
) -> db.MealPlan:
    """The new version: rows carried over from the parent (past days, meals already eaten
    today) plus the planned horizon, its shopping list (ticks kept), and the PlanStats v2
    snapshot with the logs active in the plan's dates."""
    target = decided.target
    assert target is not None
    assert read.inputs is not None
    parent = target.plan
    version = await planning.next_version(session, scope.user_id, target.start)
    # The parent's list as it is now, under the lock: ticks made while we planned carry over.
    shopping = (
        list(
            await session.scalars(
                select(db.ShoppingItem).where(db.ShoppingItem.plan_id == parent.id)
            )
        )
        if parent is not None
        else []
    )
    logs = [log for log in read.logs if log.id not in voided] + new_logs
    # A meal marked eaten that the parent still plans is carried over as that meal (status
    # eaten); its log then counts through the planner's `extra` only, never as well.
    as_meal = eaten.shown_as_meals(logs, parent)
    # Every other meal with an active slotted log is reported, not only this request's: a log
    # written while no version could be saved, or before POST /plans made the plan again, would
    # otherwise be counted on top of the planned meal it replaced.
    reported = {
        (log.eaten_on, Slot(log.slot))
        for log in logs
        if log.slot is not None and log.id not in as_meal
    }
    eaten_cells = {(log.eaten_on, Slot(log.slot)) for log in logs if log.id in as_meal}
    by_day: dict[int, list[db.MealLog]] = {}
    for log in logs:
        if target.covers(log.eaten_on) and log.id not in as_meal:
            by_day.setdefault(target.day(log.eaten_on), []).append(log)
    snapshot = [[planning.logged_out(log) for log in by_day.get(d, [])] for d in range(target.days)]

    def kept(m: db.PlanMeal, upto: int) -> bool:
        cell = (target.date(m.day), Slot(m.slot))
        frozen = m.day == decided.offset and Slot(m.slot) in decided.frozen
        return cell not in reported and (m.day < upto or frozen or cell in eaten_cells)

    solved = decided.solved
    if solved is None:  # only past days changed: carry everything over
        assert parent is not None
        rows = [m for m in parent.meals if kept(m, target.days)]
        stats = planning.PlanStats.model_validate(parent.stats)
        stats.day_totals = _copied_totals(rows, by_day, target.days, target.days)
        stats.logged = snapshot
        row = db.MealPlan(
            user_id=scope.user_id,
            start_date=target.start,
            days=target.days,
            version=version,
            parent_id=parent.id,
            planner=parent.planner,
            status=parent.status,
            objective=parent.objective,
            solve_ms=0,
            currency=parent.currency,
            stats=stats.model_dump(mode="json"),
        )
        row.meals.extend(planning.copy_meal(m) for m in rows)
        row.shopping.extend(
            db.ShoppingItem(
                food_id=s.food_id,
                grams=s.grams,
                cost_minor=s.cost_minor,
                staple=s.staple,
                checked=s.checked,
            )
            for s in shopping
        )
        session.add(row)
        await session.flush()
        return row

    offset = decided.offset
    rows = [m for m in parent.meals if kept(m, offset)] if parent is not None else []
    household = planning.household_of(read.inputs, solved.problem.days)
    stats = planning.plan_stats(
        solved.problem,
        solved.result,
        solved.plan,
        solved.violations,
        seed=target.seed,
        time_limit_ms=scope.settings.replan_time_limit_ms,
        previous=solved.previous,
        household=household,
        own=planning.own_meals(read.inputs),
        skipped=planning.skipped_meals(read.inputs),
    )
    stats.targets = planning.targets_out(planning.targets_from(read.inputs.goals, target.days))
    before = planning.PlanStats.model_validate(parent.stats) if parent is not None else None
    stats.violations = [
        v for v in (before.violations if before else []) if v.day is not None and v.day < offset
    ] + [
        planning.violation_out(v, offset, household=household, cost_minor=stats.cost_minor)
        for v in solved.violations
    ]
    stats.day_totals = _copied_totals(rows, by_day, offset, target.days)[:offset] + stats.day_totals
    stats.logged = snapshot
    pinned = {(target.day(on) - offset, slot) for (on, slot) in solved.pins} | {
        (target.day(i.on) - offset, i.slot) for i in solved.applied
    }
    prepared = planning.Prepared(
        solved.problem, version, target.seed, read.latest.id if read.latest else None
    )
    row = planning.save_plan(
        session,
        scope.user_id,
        prepared,
        solved.result,
        solved.plan,
        stats,
        read.inputs.goals.currency,
        unshoppable,
        planning.Carried(
            start=target.start,
            days=target.days,
            offset=offset,
            meals=rows,
            pinned=frozenset(pinned),
            shopping=shopping,
        ),
    )
    await session.flush()
    return row


def _copied_totals(
    rows: Iterable[db.PlanMeal], logged: dict[int, list[db.MealLog]], upto: int, days: int
) -> list[MacrosOut]:
    """Day totals of carried-over days: their meals plus their logged food."""
    totals = [Macros() for _ in range(days)]
    for m in rows:
        if m.day < upto:
            totals[m.day] += Macros(m.kcal, m.protein_g, m.fat_g, m.carbs_g)
    for d in range(min(upto, days)):
        for log in logged.get(d, []):
            totals[d] += Macros(log.kcal, log.protein_g, log.fat_g, log.carbs_g)
    return [planning.macros_out(t) for t in totals]


# --- 6. outcome -----------------------------------------------------------------------------


def _outcome(
    scope: ChangeScope,
    items: list[_Item],
    read: _Read,
    decided: _Plan,
    row: db.MealPlan | None,
    new_logs: list[db.MealLog],
) -> ReplanOutcome:
    target = decided.target
    out = ReplanOutcome(
        plan_id=row.id if row is not None else None,
        version=row.version if row is not None else None,
        fresh=row is not None and target is not None and target.fresh,
        results=[
            ChangeResult(
                index=i.index,
                intent=i.change.intent,
                date=i.on,
                slot=i.slot,
                status=i.status or "failed",
                message=i.message,
                recipe_id=i.recipe_id,
                recipe_name=i.recipe_name,
            )
            for i in items
        ],
        logged=[
            Logged(
                date=log.eaten_on,
                slot=Slot(log.slot) if log.slot else None,
                kind=planning.log_kind(log),
                description=log.description,
                kcal=log.kcal,
                estimated=log.estimated,
            )
            for log in new_logs
        ],
        notes=list(decided.notes),
    )
    if row is None or target is None or read.inputs is None:
        return out
    names = dict(read.names)
    if decided.solved is not None:
        names |= {rid: r.name for rid, r in decided.solved.problem.recipes.items()}
        out.warnings = [v.message for v in hard(decided.solved.violations)]
    if not target.fresh and read.latest is not None:
        out.changes = _diff(scope, items, read.latest, row, names)
    stats = planning.PlanStats.model_validate(row.stats)
    band = planning.targets_from(read.inputs.goals, target.days).daily[Nutrient.KCAL]
    floor = round(read.inputs.goals.calorie_floor)
    relaxed = (
        {target.date(decided.offset + d) for d in decided.solved.problem.day_kcal}
        if decided.solved is not None
        else set[date]()
    )
    changed = sorted(
        {c.date for c in out.changes}
        | {log.eaten_on for log in new_logs if target.covers(log.eaten_on)}
    )
    for on in changed:
        kcal = stats.day_totals[target.day(on)].kcal
        lo, hi = band.min or 0, band.max or kcal
        out.days.append(
            DayKcal(
                date=on,
                kcal=kcal,
                min=lo,
                max=hi,
                floor=floor,
                relaxed=on in relaxed,
                within=lo <= kcal <= hi,
            )
        )
    return out


def _diff(
    scope: ChangeScope,
    items: list[_Item],
    before: db.MealPlan,
    after: db.MealPlan,
    names: dict[int, str],
) -> list[SlotChange]:
    """Meals that differ between the parent and the new version, from today on."""

    def cells(plan: db.MealPlan) -> dict[DateSlot, db.PlanMeal]:
        return {
            (plan.start_date + timedelta(days=m.day), Slot(m.slot)): m
            for m in plan.meals
            if plan.start_date + timedelta(days=m.day) >= scope.today
        }

    old, new = cells(before), cells(after)
    causes = {i.cell: i for i in items if i.status == "applied"}
    out: list[SlotChange] = []
    for cell in sorted(old.keys() | new.keys(), key=lambda c: (c[0], SLOT_ORDER.index(c[1]))):
        a, b = old.get(cell), new.get(cell)
        same_recipe = (a.recipe_id if a else None) == (b.recipe_id if b else None)
        if same_recipe and (a.portions if a else None) == (b.portions if b else None):
            continue
        cause = causes.get(cell)
        reason: ChangeReason = (
            cause.change.intent if cause else "rebalance" if not same_recipe else "resize"
        )
        out.append(
            SlotChange(
                date=cell[0],
                slot=cell[1],
                before=names.get(a.recipe_id) if a else None,
                after=names.get(b.recipe_id) if b else None,
                after_recipe_id=b.recipe_id if b else None,
                before_portions=a.portions if a else None,
                after_portions=b.portions if b else None,
                change_index=cause.index if cause else None,
                reason=reason,
            )
        )
    return out
