"""Plan changes from the plan screen and the diary (POST /plans/replan, ADR-0015).

Typed changes (larder_llm.schemas) applied by the executor (`changes.replan.apply_changes`).
In front of it, in one short transaction:

1. `today` within a day of the clock's UTC date -> else 400 bad_today.
2. A change request already stored with this `client_id` (cravings.client_id) -> 409
   duplicate: it was applied; the client reloads the plan instead of resending.
3. The user's replan lock (changes.limits.acquire_lock) -> else 409 busy. One plan change per
   user at a time; solves still queue behind the process-wide `planning.plan_limiter`. The
   lock is released when the replan ends.

The response carries the wall time as `Server-Timing: replan;dur=<ms>` and it is logged with
the number of meals changed (churn); the saved version's stats keep it as `total_ms`.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as wall_time
from typing import Literal

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api import planning
from larder_api.changes import limits, replan
from larder_api.changes.offplan import Estimate
from larder_api.changes.scope import ChangeScope, Models
from larder_api.schemas import ChangeProblem, ReplanRequest
from larder_api.settings import Settings
from larder_db import models as db
from larder_llm.client import ModelCall
from larder_llm.outcome import ReplanOutcome

logger = logging.getLogger(__name__)

BAD_TODAY = "Your device's date looks wrong - please check it and try again."
BUSY = "Still working on your last change."
DUPLICATE = "Those changes were already made - reload your plan."


class ChangeRefused(HTTPException):
    """A refused replan; sent as a JSON ChangeProblem (see `problem_response`)."""

    def __init__(self, status_code: int, problem: ChangeProblem) -> None:
        super().__init__(status_code, problem.detail)
        self.problem = problem


async def problem_response(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ChangeRefused)
    return JSONResponse(exc.problem.model_dump(mode="json"), status_code=exc.status_code)


@dataclass(frozen=True, slots=True)
class Timed:
    outcome: ReplanOutcome
    ms: float
    churn: int  # meals whose recipe changed (or appeared / went), from today on

    @property
    def server_timing(self) -> str:
        return f"replan;dur={self.ms:.1f}"


def _refuse(
    code: Literal["bad_today", "busy", "duplicate"], detail: str, status_code: int
) -> ChangeRefused:
    return ChangeRefused(status_code, ChangeProblem(detail=[detail], code=code))


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
        if not await limits.acquire_lock(session, user_id, token, settings, now):
            raise _refuse("busy", BUSY, status.HTTP_409_CONFLICT)
        await session.commit()
        return token
    except Exception:
        await session.rollback()
        raise


def app_scope(
    user_id: int,
    *,
    today: date,
    local_time: wall_time | None,
    now: datetime,
    sessionmaker: async_sessionmaker[AsyncSession],
    catalog: planning.CatalogCache,
    planner: planning.Planner,
    settings: Settings,
    client_id: uuid.UUID | None = None,
) -> ChangeScope:
    """A scope for work started from the app's own screens, without models."""

    async def no_calls(_: ModelCall) -> None:
        raise AssertionError("app screens never call a model")

    return ChangeScope(
        user_id=user_id,
        today=today,
        local_time=local_time,
        now=now,
        sessionmaker=sessionmaker,
        catalog=catalog,
        planner=planner,
        settings=settings,
        models=Models(),
        log_call=no_calls,
        client_id=client_id,
    )


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

    scope = app_scope(
        user_id,
        today=body.today,
        local_time=body.local_time,
        now=now,
        sessionmaker=sessionmaker,
        catalog=catalog,
        planner=planner,
        settings=settings,
        client_id=body.client_id,
    )
    try:
        outcome = await replan.apply_changes(scope, body.changes, estimates=estimates)
    finally:
        await limits.release_lock(sessionmaker, user_id, token)
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
