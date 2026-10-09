"""The shopping list for a plan: what to buy after using the pantry, plus staples to check.

The total is the plan's cost (`to_minor(cost_millipence)`), the same figure the budget check
uses. Per-line costs share that total out by largest remainder, so they always add up to it.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from larder_solver.metrics import allocate, cost_millipence, staples, to_minor
from larder_solver.problem import Plan, Problem


@dataclass(frozen=True, slots=True)
class ShoppingLine:
    food_id: int
    grams: int  # 0 for staples
    cost_millipence: int
    cost_minor: int  # this line's share of ShoppingList.total_minor
    staple: bool = False  # store-cupboard item to check you have; never bought or costed


@dataclass(frozen=True, slots=True)
class ShoppingList:
    lines: tuple[ShoppingLine, ...]  # to buy, then staples; each by category, name, id
    total_minor: int


def _apportion(millipence: Mapping[int, int], total: int) -> dict[int, int]:
    """Largest remainder: whole minor units per line, then one more unit to each of the largest
    remainders until the lines add up to `total` (ties: lower food id)."""
    out = {f: m // 1000 for f, m in millipence.items()}
    spare = max(total - sum(out.values()), 0)
    for f in sorted(millipence, key=lambda f: (-(millipence[f] % 1000), f))[:spare]:
        out[f] += 1
    return out


def shopping_list(problem: Problem, plan: Plan) -> ShoppingList:
    buy = allocate(problem, plan).buy
    millipence = {f: cost_millipence(problem, {f: g}) for f, g in buy.items()}
    total = to_minor(sum(millipence.values()))
    minor = _apportion(millipence, total)

    def order(line: ShoppingLine) -> tuple[str, str, int]:
        food = problem.foods[line.food_id]
        return (food.category or "", food.name.casefold(), food.id)

    bought = [ShoppingLine(f, g, millipence[f], minor[f]) for f, g in buy.items()]
    kept = [ShoppingLine(f, 0, 0, 0, staple=True) for f in staples(problem, plan)]
    return ShoppingList((*sorted(bought, key=order), *sorted(kept, key=order)), total)
