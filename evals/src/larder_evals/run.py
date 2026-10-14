"""Scenarios, planners and scoring. Every number comes from the solver's validator and metrics
applied to the plan a planner returned, never from the planner's own report.

Per plan:
- valid: a plan came back with no hard violation (structure, safety, kcal bands, repeats,
  budget). Safety violations (allergens, diet, avoided or unknown foods, unverified recipes for
  restricted users, the calorie floor) are counted on their own: they could hurt someone.
- made-up recipes: meals naming a recipe that isn't in the problem (`unknown_recipe`).
- pantry use: share of the pantry's grams (in lots usable during the plan) the plan eats.
- waste: grams left in lots that expire within the plan.
- churn (replans): slots whose recipe changed against the plan before the change.
- latency (ms) and cost (micro-dollars; 0 for the hybrid planner).
"""

import math
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from larder_solver import Plan, PlanResult, Problem, hard, validate
from larder_solver.metrics import allocate, changed_slots
from larder_solver.scenarios import Scenario, planted, realistic, replan, synthetic_catalog
from larder_solver.validate import SAFETY_CODES, Code

if TYPE_CHECKING:
    from larder_api.planning import PlanningCatalog

__all__ = [
    "KINDS",
    "Result",
    "Scored",
    "catalog_scenarios",
    "hybrid",
    "p",
    "score",
    "synthetic_scenarios",
]

KINDS = ("planted", "realistic", "replans")

type Planner = Callable[[Problem, Plan | None], tuple[PlanResult, int]]


@dataclass(frozen=True, slots=True)
class Result:
    kind: str
    seed: int
    planner: str
    found: bool
    valid: bool
    hard_violations: int
    safety_violations: int
    unknown_recipes: int
    meals: int
    pantry_used_pct: float | None  # None: no usable pantry
    waste_g: int
    churn: int | None  # replans only
    ms: float
    cost_micro_usd: int


@dataclass(frozen=True, slots=True)
class Scored:
    kind: str
    seed: int
    scenario: Scenario


def hybrid(mode: str = "auto", time_limit_ms: int = 3_500, workers: int = 4) -> Planner:
    """The app's planner: CP-SAT when it exists, the greedy baseline standing in."""
    from larder_api.planning import run_planner  # the API package; imported lazily

    run = partial(run_planner, mode=mode, time_limit_ms=time_limit_ms, workers=workers)

    def plan(problem: Problem, previous: Plan | None) -> tuple[PlanResult, int]:
        return run(problem, previous), 0

    return plan


def synthetic_scenarios(n: int, seed: int = 0, kinds: Sequence[str] = KINDS) -> Iterator[Scored]:
    """`n` scenarios per kind over the synthetic catalogue (no database)."""
    builders: dict[str, Callable[[int], Scenario]] = {
        "planted": lambda s: planted(s),
        "realistic": lambda s: realistic(s, synthetic_catalog(s)),
        "replans": lambda s: replan(s),
    }
    for kind in kinds:
        for s in range(seed, seed + n):
            yield Scored(kind, s, builders[kind](s))


def catalog_scenarios(
    full: "PlanningCatalog", n: int, seed: int = 0, kinds: Sequence[str] = (*KINDS, "profiles")
) -> Iterator[Scored]:
    """`n` scenarios per kind over the seeded real catalogue; "profiles" are the API's ten user
    profiles built through its own make_problem (goals, allergies, diets, budgets)."""
    from larder_api.bench import profile_scenario

    catalog = full.catalog
    builders: dict[str, Callable[[int], Scenario]] = {
        "planted": lambda s: planted(s, catalog),
        "realistic": lambda s: realistic(s, catalog),
        "replans": lambda s: replan(s, catalog),
        "profiles": lambda s: profile_scenario(s, full),
    }
    for kind in kinds:
        for s in range(seed, seed + n):
            yield Scored(kind, s, builders[kind](s))


def score(item: Scored, planner_name: str, planner: Planner) -> Result:
    problem, previous = item.scenario.problem, item.scenario.previous
    started = time.perf_counter()
    result, cost = planner(problem, previous)
    ms = (time.perf_counter() - started) * 1000
    plan = result.plan
    if plan is None:
        return Result(
            item.kind, item.seed, planner_name, False, False, 0, 0, 0, 0, None, 0, None, ms, cost
        )
    violations = hard(validate(problem, plan))
    usable = sum(lot.grams for lot in problem.pantry if lot.expires is None or lot.expires >= 0)
    known = [m for m in plan.meals if m.recipe_id in problem.recipes]
    used_pct: float | None = None
    waste = 0
    if known:
        allocation = allocate(problem, Plan(tuple(known)))
        if usable:
            used_pct = 100 * sum(allocation.pantry_used.values()) / usable
        waste = sum(allocation.waste.values())
    return Result(
        kind=item.kind,
        seed=item.seed,
        planner=planner_name,
        found=True,
        valid=not violations,
        hard_violations=len(violations),
        safety_violations=sum(v.code in SAFETY_CODES for v in violations),
        unknown_recipes=sum(v.code == Code.UNKNOWN_RECIPE for v in violations),
        meals=len(plan.meals),
        pantry_used_pct=used_pct,
        waste_g=waste,
        churn=changed_slots(previous, plan) if previous is not None else None,
        ms=ms,
        cost_micro_usd=cost,
    )


def p(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (nan when empty)."""
    if not values:
        return math.nan
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]
