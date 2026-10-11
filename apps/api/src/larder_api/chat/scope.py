"""What one chat turn's tools are bound to: the signed-in user, the database, the planner and
the models. Tool handlers receive this, never a user id from the model. It carries plain values
(no ORM rows), so any step can open its own short session."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time

import anyio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api import planning
from larder_api.settings import Settings
from larder_llm.client import ChatModel, ModelCall, StructuredModel
from larder_llm.outcome import ReplanOutcome
from larder_llm.reply import OfflineReason
from larder_solver import Plan, PlanResult, Problem


@dataclass(frozen=True, slots=True)
class Models:
    """`chat is None` = offline for this turn: no key / llm_mode=offline ("no_key"), or the
    user's budget is spent ("budget"). `fast` may still be None when chat is set (tests)."""

    chat: ChatModel | None = None
    fast: StructuredModel | None = None
    offline_reason: OfflineReason | None = None

    @property
    def online(self) -> bool:
        return self.chat is not None


type Emit = Callable[[object], Awaitable[None]]  # a larder_api.schemas.ChatEvent


@dataclass(slots=True)
class ChatScope:
    user_id: int
    today: date  # the user's local date for this turn
    local_time: time | None
    now: datetime  # UTC, from the clock seam
    thread_id: int
    message_id: int  # the user's chat message this turn answers
    raw_text: str  # the user's words (stored with each change request)
    sessionmaker: async_sessionmaker[AsyncSession]
    catalog: planning.CatalogCache
    planner: planning.Planner
    settings: Settings
    models: Models
    emit: Emit  # stream an event to the client (no-op once it has gone)
    log_call: Callable[[ModelCall], Awaitable[None]]  # writes llm_calls now, own transaction
    # Collected during the turn:
    outcomes: list[ReplanOutcome] = field(default_factory=list[ReplanOutcome])
    created_recipes: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])
    cost_micro_usd: int = 0  # this turn's model spend so far (per-turn cap)

    @property
    def wrote(self) -> bool:
        """A write tool changed something this turn: never run the offline path after this."""
        return bool(self.outcomes or self.created_recipes)

    async def solve(self, problem: Problem, previous: Plan | None) -> PlanResult:
        """Run the planner in a worker thread behind planning.plan_limiter(settings). The
        planner carries its own time budget (routers.plans.get_replan_planner:
        settings.replan_time_limit_ms per run)."""
        return await anyio.to_thread.run_sync(
            self.planner, problem, previous, limiter=planning.plan_limiter(self.settings)
        )
