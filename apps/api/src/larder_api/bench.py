"""Planner benchmark on the real catalog: `make bench` / `uv run larder-bench --help`.

Generates planted (a valid plan is known to exist) and realistic (user-like) problems from the
seeded recipes, runs a planner on each, checks every plan with the independent validator and
reports validity and latency. The M3 gate: no hard violations, end-to-end p95 < 5 s.
"""

import argparse
import asyncio
import math
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from larder_api.planning import load_catalog, run_planner
from larder_db.engine import make_engine, make_sessionmaker
from larder_solver import (
    Catalog,
    PlanResult,
    Problem,
    Status,
    hard,
    score,
    shopping_list,
    validate,
)
from larder_solver.scenarios import Scenario, planted, realistic


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


async def load(database_url: str | None) -> Catalog:
    engine = make_engine(database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            return (await load_catalog(session)).catalog
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="larder-bench", description=__doc__)
    parser.add_argument("--planner", choices=["auto", "cpsat", "greedy"], default="auto")
    parser.add_argument("--n", type=int, default=20, help="scenarios per kind")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--kinds", default="planted,realistic")
    parser.add_argument("--time-limit-ms", type=int, default=3_500)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--concurrency", type=int, default=1, help="plans solved at once")
    parser.add_argument("--database-url")
    parser.add_argument("--out", help="also write the Markdown report here")
    args = parser.parse_args(argv)

    catalog = asyncio.run(load(args.database_url))
    builders: dict[str, Callable[[int], Scenario]] = {
        "planted": lambda s: planted(s, catalog),
        "realistic": lambda s: realistic(s, catalog),
    }

    def plan(problem: Problem) -> PlanResult:
        return run_planner(problem, args.planner, args.time_limit_ms, args.workers)

    jobs = [
        (kind, seed)
        for kind in args.kinds.split(",")
        for seed in range(args.seed, args.seed + args.n)
    ]
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        runs = list(
            pool.map(lambda job: one(job[0], job[1], lambda: builders[job[0]](job[1]), plan), jobs)
        )
    report = render(args.planner, runs)
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)


if __name__ == "__main__":
    main(sys.argv[1:])
