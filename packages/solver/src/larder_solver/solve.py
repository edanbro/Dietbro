"""CP-SAT weekly planner: `solve(problem, previous, time_limit_ms) -> PlanResult`.

Eduard's to write (PLAN.md §11). The modelling guide is docs/DESIGN.md §8 and
packages/solver/README.md; the specification is packages/solver/tests/test_solve.py, which
passes once this is implemented. Check any plan with `larder_solver.validate`.
"""

from larder_solver.problem import Plan, PlanResult, Problem


def solve(
    problem: Problem,
    previous: Plan | None = None,
    time_limit_ms: int = 5_000,
    *,
    workers: int = 8,
) -> PlanResult:
    raise NotImplementedError("CP-SAT model not written yet: see packages/solver/README.md")
