"""Planner benchmark on the real catalog: `make bench` / `uv run larder-bench --help`.

Generates planted (a valid plan is known to exist), realistic (user-like) and replan (mid-week
changes) problems from the seeded recipes, runs a planner on each, checks every plan with
the independent validator and reports validity and latency. The M3 gate: no hard violations,
end-to-end p95 < 5 s.

Replan mode (`make bench-replan`, M5: replan p95 < 1 s at the API, average churn reported):

- `replan-scenarios`: `scenarios.replan` problems over the seeded recipes, planned with the plan
  before the change as `previous`; latency of plan + validate, churn = slots changed vs
  `previous` (`metrics.changed_slots`) next to the forced churn (cells the change emptied).
- `replan-api`: the executor itself (`changes.replan.apply_changes`, what POST /plans/replan
  runs) against the database: throwaway users (the ten PROFILES) each get a plan made
  like POST /plans, then a seeded mix of skips, swaps, cravings and off-plan meals on Wednesday
  noon; latency per call (reads, prefilter, planner runs, validation, save), churn = meals that
  changed recipe vs the parent version from today on, and how many of those nobody asked for
  (rebalance). The users are deleted afterwards. Needs a migrated, seeded database.
"""

import argparse
import asyncio
import math
import statistics
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from functools import partial
from random import Random
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api import planning
from larder_api.changes.replan import apply_changes
from larder_api.changes.scope import ChangeScope, Models
from larder_api.planning import (
    PlanningCatalog,
    UserInputs,
    load_catalog,
    make_problem,
    run_planner,
)
from larder_api.settings import Settings
from larder_core.meals import Slot
from larder_db import models as db
from larder_db.engine import make_engine, make_sessionmaker
from larder_llm.client import ModelCall
from larder_llm.schemas import AteOffPlan, Change, Craving, OffPlanItem, Skip, Swap, When
from larder_solver import (
    Catalog,
    Plan,
    PlanResult,
    Problem,
    Status,
    hard,
    score,
    shopping_list,
    validate,
)
from larder_solver.metrics import changed_slots
from larder_solver.scenarios import Scenario, forced_churn, planted, realistic, replan


@dataclass(frozen=True, slots=True)
class Run:
    kind: str
    seed: int
    status: Status
    hard_violations: int
    solve_ms: float
    total_ms: float
    terms: dict[str, int]


def p(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile."""
    if not values:
        return math.nan
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def one(
    kind: str, seed: int, build: Callable[[], Scenario], plan: Callable[[Problem], PlanResult]
) -> Run:
    """End to end = build the problem (prefilter included) + plan + validate + shopping list."""
    t0 = time.perf_counter()
    problem = build().problem
    t1 = time.perf_counter()
    result = plan(problem)
    t2 = time.perf_counter()
    violations: list[object] = []
    terms: dict[str, int] = {}
    if result.plan is not None:
        violations = list(hard(validate(problem, result.plan)))
        terms = score(problem, result.plan).terms
        shopping_list(problem, result.plan)
    t3 = time.perf_counter()
    return Run(
        kind=kind,
        seed=seed,
        status=result.status,
        hard_violations=len(violations),
        solve_ms=(t2 - t1) * 1000,
        total_ms=(t3 - t0) * 1000,
        terms=terms,
    )


def _pct(k: int, n: int) -> str:
    return f"{100 * k / n:.0f}%" if n else "n/a"


def render(planner: str, runs: Sequence[Run]) -> str:
    lines = [
        f"## Planner benchmark: `{planner}`",
        "",
        "| Scenarios | n | Plan found | Found plans with no hard violations | Infeasible | "
        "Timed out | Solve p50 / p95 / max (ms) | End-to-end p50 / p95 (ms) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for kind in sorted({r.kind for r in runs}):
        rs = [r for r in runs if r.kind == kind]
        found = [r for r in rs if r.status in (Status.OPTIMAL, Status.FEASIBLE)]
        valid = [r for r in found if r.hard_violations == 0]
        solve = [r.solve_ms for r in rs]
        total = [r.total_ms for r in rs]
        lines.append(
            f"| {kind} | {len(rs)} | {_pct(len(found), len(rs))} | "
            f"{_pct(len(valid), len(found))} | "
            f"{_pct(sum(r.status == Status.INFEASIBLE for r in rs), len(rs))} | "
            f"{_pct(sum(r.status == Status.UNKNOWN for r in rs), len(rs))} | "
            f"{p(solve, 0.5):.0f} / {p(solve, 0.95):.0f} / {max(solve):.0f} | "
            f"{p(total, 0.5):.0f} / {p(total, 0.95):.0f} |"
        )
    found = [r for r in runs if r.terms]
    if found:
        lines += ["", "Mean objective terms (millipence) over plans found:", ""]
        lines += [
            f"- {term}: {statistics.fmean(r.terms[term] for r in found):,.0f}"
            for term in found[0].terms
        ]
    return "\n".join(lines) + "\n"


async def load(database_url: str | None) -> PlanningCatalog:
    engine = make_engine(database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            return await load_catalog(session)
    finally:
        await engine.dispose()


# User-like profiles that go through the API's own make_problem (goals, allergies, diet).
PROFILES: list[dict[str, Any]] = [
    {"kcal": (1800, 2200), "protein": 100},
    {"kcal": (1400, 1600), "protein": 90, "budget": 3500},
    {"kcal": (2400, 2800), "protein": 140},
    {"kcal": (1700, 2000), "protein": 80, "diet": "vegetarian"},
    {"kcal": (1700, 2000), "protein": 70, "diet": "vegan"},
    {"kcal": (1600, 1900), "protein": 90, "allergens": ["gluten", "milk"]},
    {"kcal": (1800, 2100), "protein": 100, "allergens": ["peanuts", "tree_nuts"]},
    {"kcal": (1600, 1900), "protein": 70, "diet": "vegan", "allergens": ["soy"]},
    {"kcal": (2000, 2300), "protein": 110, "allergens": ["fish", "crustaceans", "molluscs"]},
    {"kcal": (1500, 1800), "protein": 90, "allergens": ["eggs", "milk"], "budget": 4000},
]


def profile_scenario(seed: int, catalog: PlanningCatalog) -> Scenario:
    spec = PROFILES[seed % len(PROFILES)]
    lo, hi = spec["kcal"]
    inputs = UserInputs(
        goals=db.Goals(
            kcal_min=lo,
            kcal_max=hi,
            calorie_floor=1200,
            max_daily_deficit=1000,
            protein_g_min=spec["protein"],
            weekly_budget_minor=spec.get("budget"),
            currency="GBP",
        ),
        allergies=db.Allergies(allergens=spec.get("allergens", []), avoid_food_ids=[]),
        preferences=db.Preferences(
            diet=spec.get("diet"),
            liked_cuisines=[],
            disliked_cuisines=[],
            liked_food_ids=[],
            disliked_food_ids=[],
        ),
    )
    start = date(2026, 10, 12)
    return Scenario(make_problem(inputs, catalog, start, seed=seed), None)


# --- replans (M5) -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplanRun:
    kind: str
    seed: int
    found: bool
    hard_violations: int
    ms: float  # replan-scenarios: plan + validate; replan-api: the whole executor call
    churn: int  # meals whose recipe changed (or appeared / went)
    forced: int  # of those, the ones the request itself needed (emptied or asked-for cells)


def replan_scenario_run(
    seed: int, catalog: Catalog, plan: Callable[[Problem, Plan | None], PlanResult]
) -> ReplanRun:
    scenario = replan(seed, catalog)
    problem = scenario.problem
    t0 = time.perf_counter()
    result = plan(problem, scenario.previous)
    violations = hard(validate(problem, result.plan)) if result.plan is not None else []
    ms = (time.perf_counter() - t0) * 1000
    return ReplanRun(
        kind="replan-scenarios",
        seed=seed,
        found=result.plan is not None,
        hard_violations=len(violations),
        ms=ms,
        churn=changed_slots(scenario.previous, result.plan) if result.plan else 0,
        forced=forced_churn(scenario),
    )


BENCH_MONDAY = date(2026, 10, 12)
BENCH_TODAY = BENCH_MONDAY + timedelta(days=2)  # Wednesday, noon: breakfast is over
BENCH_NOON = clock_time(12, 0)
_DISHES = ("pasta", "curry", "chicken", "soup", "salad", "rice")
_TAGS = ("spicy", "quick", "light", "vegetarian")


def random_change(rng: Random) -> Change:
    """A plausible plan-screen change from Wednesday noon to Sunday."""
    on = BENCH_TODAY + timedelta(days=rng.randint(0, 4))
    slot = rng.choice([Slot.LUNCH, Slot.DINNER] if on == BENCH_TODAY else list(Slot))
    when = When(date=on, slot=slot)
    kind = rng.choice(["skip", "swap", "craving", "craving", "ate"])
    if kind == "skip":
        return Skip(intent="skip", when=when, eating_elsewhere=rng.random() < 0.5)
    if kind == "swap":
        return Swap(intent="swap", when=when)
    if kind == "ate":
        when = When(date=BENCH_TODAY, slot=Slot.LUNCH)
        item = OffPlanItem(name="pizza", quantity=f"{rng.randint(1, 4)} slices")
        return AteOffPlan(intent="ate_off_plan", when=when, description="pizza", items=[item])
    return Craving(
        intent="craving",
        when=when,
        dish=rng.choice(_DISHES) if rng.random() < 0.5 else None,
        tags=[rng.choice(_TAGS)],
        strength=rng.choice(["hard", "soft"]),
    )


async def _bench_user(session: AsyncSession, spec: dict[str, Any]) -> int:
    lo, hi = spec["kcal"]
    user = db.User(auth_subject=f"bench:{uuid.uuid4()}")
    session.add(user)
    await session.flush()
    session.add_all(
        [
            db.Goals(
                user_id=user.id,
                kcal_min=lo,
                kcal_max=hi,
                calorie_floor=1200,
                max_daily_deficit=1000,
                protein_g_min=spec["protein"],
                weekly_budget_minor=spec.get("budget"),
                currency="GBP",
            ),
            db.Allergies(user_id=user.id, allergens=spec.get("allergens", []), avoid_food_ids=[]),
            db.Preferences(
                user_id=user.id,
                diet=spec.get("diet"),
                liked_cuisines=[],
                disliked_cuisines=[],
                liked_food_ids=[],
                disliked_food_ids=[],
            ),
        ]
    )
    await session.flush()
    return user.id


async def _first_plan(
    maker: async_sessionmaker[AsyncSession],
    user_id: int,
    cache: planning.CatalogCache,
    planner: planning.Planner,
) -> bool:
    """A week from Monday, made the way POST /plans makes it; False if none fits."""
    async with maker() as session:
        user = await session.get(db.User, user_id)
        assert user is not None
        inputs = await planning.load_inputs(session, user)
        catalog = await cache.get(maker)
        seed = planning.plan_seed(user_id, BENCH_MONDAY, 1)
        problem = planning.make_problem(inputs, catalog, BENCH_MONDAY, seed=seed)
        result = planner(problem, None)
        try:
            plan, violations = planning.check_outcome(problem, result)
        except planning.PlanningError:
            return False
        stats = planning.plan_stats(problem, result, plan, violations, seed=seed, time_limit_ms=0)
        prepared = planning.Prepared(problem, 1, seed, None)
        planning.save_plan(
            session, user_id, prepared, result, plan, stats, "GBP", catalog.unshoppable
        )
        await session.commit()
    return True


async def api_replans(
    database_url: str | None,
    n: int,
    seed: int,
    planner: planning.Planner,
    per_user: int = 4,
) -> list[ReplanRun]:
    """`n` executor calls, `per_user` per throwaway user (see the module docstring)."""
    engine = make_engine(database_url)
    maker = make_sessionmaker(engine)
    cache = planning.CatalogCache()
    settings = Settings()
    users: list[int] = []
    runs: list[ReplanRun] = []

    async def no_calls(_: ModelCall) -> None:
        raise AssertionError("offline")

    try:
        await cache.get(maker)  # the API keeps it warm (CATALOG_TTL_S)
        u = 0
        while len(runs) < n:
            async with maker() as session:
                user_id = await _bench_user(session, PROFILES[(seed + u) % len(PROFILES)])
                await session.commit()
            users.append(user_id)
            u += 1
            if not await _first_plan(maker, user_id, cache, planner):
                continue
            for j in range(min(per_user, n - len(runs))):
                run_seed = seed * 10_000 + u * 100 + j
                rng = Random(run_seed)
                changes = [random_change(rng) for _ in range(rng.choice([1, 1, 1, 2]))]
                scope = ChangeScope(
                    user_id=user_id,
                    today=BENCH_TODAY,
                    local_time=BENCH_NOON,
                    now=datetime.combine(BENCH_TODAY, BENCH_NOON, UTC),
                    sessionmaker=maker,
                    catalog=cache,
                    planner=planner,
                    settings=settings,
                    models=Models(),
                    log_call=no_calls,
                    client_id=uuid.uuid4(),
                )
                t0 = time.perf_counter()
                outcome = await apply_changes(scope, changes)
                ms = (time.perf_counter() - t0) * 1000
                moved = [c for c in outcome.changes if c.reason != "resize"]
                runs.append(
                    ReplanRun(
                        kind="replan-api",
                        seed=run_seed,
                        found=outcome.plan_id is not None,
                        hard_violations=len(outcome.warnings),
                        ms=ms,
                        churn=len(moved),
                        forced=sum(c.reason != "rebalance" for c in moved),
                    )
                )
    finally:
        async with maker() as session:
            if users:
                await session.execute(delete(db.User).where(db.User.id.in_(users)))
                await session.commit()
        await engine.dispose()
    return runs


def render_replans(planner: str, runs: Sequence[ReplanRun]) -> str:
    lines = [
        f"## Replan benchmark: `{planner}`",
        "",
        "| Kind | n | Saved / found | No hard violations | Latency p50 / p95 / max (ms) | "
        "Churn: changed meals (mean) | of which forced or asked for | unrequested |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for kind in sorted({r.kind for r in runs}):
        rs = [r for r in runs if r.kind == kind]
        found = [r for r in rs if r.found]
        ms = [r.ms for r in rs]
        churn = statistics.fmean(r.churn for r in found) if found else math.nan
        forced = statistics.fmean(r.forced for r in found) if found else math.nan
        lines.append(
            f"| {kind} | {len(rs)} | {_pct(len(found), len(rs))} | "
            f"{_pct(sum(r.hard_violations == 0 for r in found), len(found))} | "
            f"{p(ms, 0.5):.0f} / {p(ms, 0.95):.0f} / {max(ms):.0f} | "
            f"{churn:.1f} | {forced:.1f} | {churn - forced:.1f} |"
        )
    return "\n".join(lines) + "\n"


REPLAN_KINDS = ("replan-scenarios", "replan-api")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="larder-bench", description=__doc__)
    parser.add_argument("--planner", choices=["auto", "cpsat", "greedy"], default="auto")
    parser.add_argument("--n", type=int, default=20, help="scenarios per kind")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--kinds",
        default="planted,realistic,profiles,replans",
        help="planted, realistic, profiles, replans; replan mode: replan-scenarios, replan-api",
    )
    parser.add_argument("--time-limit-ms", type=int, default=3_500)
    parser.add_argument(
        "--replan-time-limit-ms", type=int, default=1_000, help="per planner run in a replan"
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--concurrency", type=int, default=1, help="plans solved at once")
    parser.add_argument("--database-url")
    parser.add_argument("--out", help="also write the Markdown report here")
    args = parser.parse_args(argv)

    kinds = args.kinds.split(",")
    replan_kinds = [k for k in kinds if k in REPLAN_KINDS]
    kinds = [k for k in kinds if k not in REPLAN_KINDS]
    full = asyncio.run(load(args.database_url))
    catalog = full.catalog
    reports: list[str] = []
    if replan_kinds:
        replanner = partial(
            run_planner,
            mode=args.planner,
            time_limit_ms=args.replan_time_limit_ms,
            workers=args.workers,
        )
        replans: list[ReplanRun] = []
        if "replan-scenarios" in replan_kinds:
            seeds = range(args.seed, args.seed + args.n)
            replans += [replan_scenario_run(s, catalog, replanner) for s in seeds]
        if "replan-api" in replan_kinds:
            replans += asyncio.run(api_replans(args.database_url, args.n, args.seed, replanner))
        reports.append(render_replans(args.planner, replans))
    builders: dict[str, Callable[[int], Scenario]] = {
        "planted": lambda s: planted(s, catalog),
        "realistic": lambda s: realistic(s, catalog),
        "profiles": lambda s: profile_scenario(s, full),
        # Mid-week replans (ADR-0014): logged intake, per-day kcal bands, chosen meals.
        "replans": lambda s: replan(s, catalog),
    }

    def plan(problem: Problem) -> PlanResult:
        return run_planner(problem, None, args.planner, args.time_limit_ms, args.workers)

    def run(job: tuple[str, int]) -> Run:
        kind, seed = job
        return one(kind, seed, lambda: builders[kind](seed), plan)

    jobs = [(kind, seed) for kind in kinds for seed in range(args.seed, args.seed + args.n)]
    if jobs:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            runs = list(pool.map(run, jobs))
        reports.insert(0, render(args.planner, runs))
    report = "\n".join(reports)
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)


if __name__ == "__main__":
    main(sys.argv[1:])
