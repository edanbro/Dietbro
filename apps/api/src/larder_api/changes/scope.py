"""What a plan change is bound to: the signed-in user, the database, the planner and the
models. It carries plain values (no ORM rows), so any step can open its own short session."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, time

import anyio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api import planning
from larder_api.settings import Settings
from larder_llm.client import ModelCall, StructuredModel
from larder_solver import Plan, PlanResult, Problem


@dataclass(frozen=True, slots=True)
class Models:
    """`fast` is None without a key (or llm_mode=offline) or once the user's budget is spent:
    callers then use their offline path."""

    fast: StructuredModel | None = None


@dataclass(slots=True)
class ChangeScope:
    user_id: int
    today: date  # the user's local date
    local_time: time | None
    now: datetime  # UTC, from the clock seam
    sessionmaker: async_sessionmaker[AsyncSession]
    catalog: planning.CatalogCache
    planner: planning.Planner
    settings: Settings
    models: Models
    log_call: Callable[[ModelCall], Awaitable[None]]  # writes llm_calls now, own transaction
    client_id: uuid.UUID | None = None  # the request's id (idempotency)

    async def solve(self, problem: Problem, previous: Plan | None) -> PlanResult:
        """Run the planner in a worker thread behind planning.plan_limiter(settings). The
        planner carries its own time budget (routers.plans.get_replan_planner:
        settings.replan_time_limit_ms per run)."""
        return await anyio.to_thread.run_sync(
            self.planner, problem, previous, limiter=planning.plan_limiter(self.settings)
        )
