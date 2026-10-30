"""Per-user model budget, the replan lock, and call logging.

- Model budget (UTC calendar month, from llm_calls.cost_micro_usd): the model is used while
  spent_month < monthly cap AND spent_today < (cap - spent_before_today) / days_left_in_month
  (pacing, so $1 lasts the month). Otherwise callers fall back to their offline path.
- Replan lock (Postgres, no Redis): users.replan_lock_token/at taken with `UPDATE users SET ...
  WHERE id = :id AND (replan_lock_token IS NULL OR replan_lock_at < now() - (deadline + 30 s))
  RETURNING id`; released by token in a `finally` (shielded from cancellation, 5 s timeout).
  One plan change per user at a time; solves still queue behind `planning.plan_limiter`.
- log_call: one llm_calls row per ModelCall in its own short transaction, written as soon as
  the call is reported (shielded), priced with larder_llm.pricing.call_cost_micro_usd.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta

import anyio
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api.settings import Settings
from larder_db import models as db
from larder_llm.client import ModelCall
from larder_llm.pricing import call_cost_micro_usd

LOCK_GRACE = timedelta(seconds=30)  # a lock older than the replan deadline + this is stale
_CLEANUP_S = 5.0  # shielded DB writes (lock release, call logs) give up after this


def micro_usd(usd: float) -> int:
    return round(usd * 1_000_000)


def _midnight(d: date) -> datetime:
    return datetime.combine(d, time(), UTC)


def _next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


async def model_allowed(
    session: AsyncSession, user_id: int, settings: Settings, now: datetime
) -> bool:
    """True while the user's spend is under the month's cap and today's paced share of it."""
    today = now.astimezone(UTC).date()
    month_start, day_start = _midnight(today.replace(day=1)), _midnight(today)
    spent_month, spent_today = (
        await session.execute(
            select(
                func.coalesce(func.sum(db.LlmCall.cost_micro_usd), 0),
                func.coalesce(
                    func.sum(db.LlmCall.cost_micro_usd).filter(db.LlmCall.created_at >= day_start),
                    0,
                ),
            ).where(db.LlmCall.user_id == user_id, db.LlmCall.created_at >= month_start)
        )
    ).one()
    cap = micro_usd(settings.llm_monthly_cap_usd)
    if spent_month >= cap:
        return False
    days_left = (_next_month(today) - today).days  # today included
    return spent_today < (cap - (spent_month - spent_today)) // days_left


def _stale_before(settings: Settings, now: datetime) -> datetime:
    return now - timedelta(seconds=settings.replan_deadline_s) - LOCK_GRACE


async def acquire_lock(
    session: AsyncSession, user_id: int, token: uuid.UUID, settings: Settings, now: datetime
) -> bool:
    taken = await session.scalar(
        update(db.User)
        .where(
            db.User.id == user_id,
            or_(
                db.User.replan_lock_token.is_(None),
                db.User.replan_lock_at < _stale_before(settings, now),
            ),
        )
        .values(replan_lock_token=token, replan_lock_at=now)
        .returning(db.User.id)
        .execution_options(synchronize_session=False)
    )
    return taken is not None


async def release_lock(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int, token: uuid.UUID
) -> None:
    with anyio.CancelScope(shield=True), anyio.move_on_after(_CLEANUP_S):
        async with sessionmaker() as session, session.begin():
            await session.execute(
                update(db.User)
                .where(db.User.id == user_id, db.User.replan_lock_token == token)
                .values(replan_lock_token=None, replan_lock_at=None)
                .execution_options(synchronize_session=False)
            )


async def log_call(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: int,
    call: ModelCall,
) -> int:
    """Insert the llm_calls row; returns its cost in micro-dollars."""
    cost = call_cost_micro_usd(call)
    usage = call.usage
    with anyio.CancelScope(shield=True), anyio.move_on_after(_CLEANUP_S):
        async with sessionmaker() as session, session.begin():
            session.add(
                db.LlmCall(
                    user_id=user_id,
                    purpose=call.purpose[:32],
                    model=call.model[:64],
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_input_tokens,
                    cache_write_tokens=usage.cache_creation_input_tokens,
                    cost_micro_usd=cost,
                    latency_ms=call.latency_ms,
                    status=call.status,
                    request_id=call.request_id[:64] if call.request_id else None,
                    error=call.error,
                )
            )
    return cost
