"""Plan changes from the plan screen, without the chat (POST /plans/replan, ADR-0015).

The same typed changes the chat's model and offline parser produce (larder_llm.schemas), applied
by the same executor (`chat.replan.apply_changes`, source "app") in a scope with no thread,
message or models. In front of it, in one short transaction:

1. `today` within a day of the clock's UTC date -> else 400 bad_today.
2. A change request already stored with this `client_id` (cravings.client_id) -> 409
   duplicate: it was applied; the client reloads the plan instead of resending.
3. The user's turn lock (chat.limits.acquire_turn, shared with chat turns) -> else 409 busy.
   One plan change per user at a time, chat or plan screen; solves still queue behind the
   process-wide `planning.plan_limiter`. The lock is released when the replan ends.

The response carries the wall time as `Server-Timing: replan;dur=<ms>` and it is logged with
the number of meals changed (churn); the saved version's stats keep it as `total_ms`.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api import planning
from larder_api.chat import limits, replan
from larder_api.chat.gate import BAD_TODAY, BUSY, ChatRefused, Code
from larder_api.chat.offplan import Estimate
from larder_api.chat.scope import ChatScope, Models
from larder_api.schemas import ChatProblem, ReplanRequest
from larder_api.settings import Settings
from larder_db import models as db
from larder_llm.client import ModelCall
from larder_llm.outcome import ReplanOutcome

logger = logging.getLogger(__name__)

DUPLICATE = "Those changes were already made - reload your plan."


@dataclass(frozen=True, slots=True)
class Timed:
    outcome: ReplanOutcome
    ms: float
    churn: int  # meals whose recipe changed (or appeared / went), from today on

    @property
    def server_timing(self) -> str:
        return f"replan;dur={self.ms:.1f}"


def _refuse(
    code: Code, detail: str, status_code: int, message_id: int | None = None
) -> ChatRefused:
    problem = ChatProblem(detail=[detail], code=code, message_id=message_id)
    return ChatRefused(status_code, problem)


async def _gate(
    session: AsyncSession, user_id: int, body: ReplanRequest, settings: Settings, now: datetime
) -> uuid.UUID:
    """Steps 1-3; returns the turn lock's token (committed)."""
    try:
        if abs((body.today - now.astimezone(UTC).date()).days) > 1:
            raise _refuse("bad_today", BAD_TODAY, status.HTTP_400_BAD_REQUEST)
        seen = await session.scalar(
            select(db.Craving.id)
            .where(db.Craving.user_id == user_id, db.Craving.client_id == body.client_id)
            .limit(1)
        )
        if seen is not None:
            raise _refuse("duplicate", DUPLICATE, status.HTTP_409_CONFLICT)
        token = uuid.uuid4()
        if not await limits.acquire_turn(session, user_id, token, settings, now):
            running = await limits.turn_in_progress(session, user_id, settings, now)
            pending = running[0] if running else None
            raise _refuse("busy", BUSY, status.HTTP_409_CONFLICT, pending)
        await session.commit()
        return token
    except Exception:
        await session.rollback()
        raise


async def run(
    session: AsyncSession,
    user_id: int,
    body: ReplanRequest,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    catalog: planning.CatalogCache,
    planner: planning.Planner,
    settings: Settings,
    now: datetime,
    estimates: dict[int, Estimate] | None = None,
) -> Timed:
    token = await _gate(session, user_id, body, settings, now)
    started = time.perf_counter()

    async def nothing(_: object) -> None:
        return None

    async def no_calls(_: ModelCall) -> None:
        raise AssertionError("a plan-screen replan never calls a model")

    scope = ChatScope(
        user_id=user_id,
        today=body.today,
        local_time=body.local_time,
        now=now,
        thread_id=None,
        message_id=None,
        raw_text="",
        sessionmaker=sessionmaker,
        catalog=catalog,
        planner=planner,
        settings=settings,
        models=Models(offline_reason="no_key"),
        emit=nothing,
        log_call=no_calls,
        client_id=body.client_id,
    )
    try:
        outcome = await replan.apply_changes(scope, body.changes, source="app", estimates=estimates)
    finally:
        await limits.release_turn(sessionmaker, user_id, token)
    timed = Timed(
        outcome,
        (time.perf_counter() - started) * 1000,
        sum(c.reason != "resize" for c in outcome.changes),
    )
    logger.info(
        "replan user=%s changes=%d applied=%d version=%s churn=%d ms=%.0f",
        user_id,
        len(body.changes),
        sum(r.status == "applied" for r in outcome.results),
        outcome.version,
        timed.churn,
        timed.ms,
    )
    return timed
