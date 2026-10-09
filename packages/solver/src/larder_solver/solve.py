"""CP-SAT weekly planner: `solve(problem, previous, time_limit_ms) -> PlanResult`.

Eduard's to write (PLAN.md §11). The modelling guide is packages/solver/README.md (overview in
docs/DESIGN.md §8); the specification is packages/solver/tests/test_solve.py, which passes once
this is implemented. Check any plan with `larder_solver.validate`.

The default time limit leaves ~1.5 s of the 5 s p95 budget for loading inputs, the prefilter,
validation and saving. Use at most `workers` search threads, capped at the CPU count.
"""

from larder_solver.problem import Plan, PlanResult, Problem


def solve(
    problem: Problem,
    previous: Plan | None = None,
    time_limit_ms: int = 3_500,
    *,
    workers: int = 8,
) -> PlanResult:
    raise NotImplementedError("CP-SAT model not written yet: see packages/solver/README.md")
