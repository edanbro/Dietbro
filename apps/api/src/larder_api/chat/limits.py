"""Per-user limits, the chat turn lock, and call logging.

- Messages: the user's chat messages (role=user) in the last 24 hours (rolling), offline turns
  included. At the limit the gate answers 429 code=daily_limit with `retry_at` = when the oldest
  of them turns 24 h old.
- Model budget (UTC calendar month, from llm_calls.cost_micro_usd): the model is used while
  spent_month < monthly cap AND spent_today < (cap - spent_before_today) / days_left_in_month
  (pacing, so $1 lasts the month). Otherwise the turn runs offline with reason "budget" and
  `resets_at` = next UTC midnight (pacing) or the 1st of next month (cap). Within a turn, the
  agent stops starting new model rounds once the turn's cost passes llm_turn_cap_usd.
- Turn lock (Postgres, no Redis): users.chat_turn_token/started_at/message_id taken with
  `UPDATE users SET ... WHERE id = :id AND (chat_turn_token IS NULL OR chat_turn_started_at <
  now() - (deadline + 30 s)) RETURNING id`; released by token in the turn task's `finally`
  (shielded from cancellation, 5 s timeout).
- log_call: one llm_calls row per ModelCall in its own short transaction, written as soon as
  the call is reported (shielded), priced with larder_llm.pricing.call_cost_micro_usd.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import cast

import anyio
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api.settings import Settings
from larder_db import models as db
from larder_llm.client import ModelCall
from larder_llm.pricing import call_cost_micro_usd
from larder_llm.reply import OfflineReason

WINDOW = timedelta(hours=24)
LOCK_GRACE = timedelta(seconds=30)  # a lock older than the turn deadline + this is stale
_CLEANUP_S = 5.0  # shielded DB writes (lock release, call logs) give up after this


@dataclass(frozen=True, slots=True)
class Budget:
    online: bool
    reason: OfflineReason | None  # None when online
    resets_at: datetime | None
    turn_cap_micro_usd: int  # min(llm_turn_cap, what pacing allows today)


def micro_usd(usd: float) -> int:
    return round(usd * 1_000_000)


async def messages_last_24h(
    session: AsyncSession, user_id: int, now: datetime
) -> tuple[int, datetime | None]:
    """(count, when the oldest counted message turns 24 h old)."""
    row = (
        await session.execute(
            select(func.count(db.ChatMessage.id), func.min(db.ChatMessage.created_at)).where(
                db.ChatMessage.user_id == user_id,
                db.ChatMessage.role == "user",
                db.ChatMessage.created_at > now - WINDOW,
            )
        )
    ).one()
    count: int = row[0]
    oldest = cast(datetime | None, row[1])  # NULL when there are none
    return count, (oldest + WINDOW if oldest is not None else None)


def _midnight(d: date) -> datetime:
    return datetime.combine(d, time(), UTC)


def _next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


async def budget(session: AsyncSession, user_id: int, settings: Settings, now: datetime) -> Budget:
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
    next_month = _next_month(today)
    if spent_month >= cap:
        return Budget(False, "budget", _midnight(next_month), 0)
    days_left = (next_month - today).days  # today included
    allowed_today = (cap - (spent_month - spent_today)) // days_left
    if spent_today >= allowed_today:
        return Budget(False, "budget", _midnight(today + timedelta(days=1)), 0)
    turn_cap = min(micro_usd(settings.llm_turn_cap_usd), allowed_today - spent_today)
    return Budget(True, None, None, turn_cap)


def _stale_before(settings: Settings, now: datetime) -> datetime:
    return now - timedelta(seconds=settings.chat_turn_deadline_s) - LOCK_GRACE


async def acquire_turn(
    session: AsyncSession, user_id: int, token: uuid.UUID, settings: Settings, now: datetime
) -> bool:
    taken = await session.scalar(
        update(db.User)
        .where(
            db.User.id == user_id,
            or_(
                db.User.chat_turn_token.is_(None),
                db.User.chat_turn_started_at < _stale_before(settings, now),
            ),
        )
        .values(chat_turn_token=token, chat_turn_started_at=now, chat_turn_message_id=None)
        .returning(db.User.id)
        .execution_options(synchronize_session=False)
    )
    return taken is not None


async def turn_in_progress(
    session: AsyncSession, user_id: int, settings: Settings, now: datetime
) -> tuple[int | None, datetime] | None:
    """(the user's message being answered, when the turn started) while a turn holds the lock."""
    row = (
        await session.execute(
            select(
                db.User.chat_turn_token,
                db.User.chat_turn_started_at,
                db.User.chat_turn_message_id,
            ).where(db.User.id == user_id)
        )
    ).one_or_none()
    if row is None or row.chat_turn_token is None or row.chat_turn_started_at is None:
        return None
    if row.chat_turn_started_at < _stale_before(settings, now):
        return None
    return row.chat_turn_message_id, row.chat_turn_started_at


async def set_turn_message(session: AsyncSession, user_id: int, token: uuid.UUID, mid: int) -> None:
    await session.execute(
        update(db.User)
        .where(db.User.id == user_id, db.User.chat_turn_token == token)
        .values(chat_turn_message_id=mid)
        .execution_options(synchronize_session=False)
    )


async def release_turn(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int, token: uuid.UUID
) -> None:
    with anyio.CancelScope(shield=True), anyio.move_on_after(_CLEANUP_S):
        async with sessionmaker() as session, session.begin():
            await session.execute(
                update(db.User)
                .where(db.User.id == user_id, db.User.chat_turn_token == token)
                .values(chat_turn_token=None, chat_turn_started_at=None, chat_turn_message_id=None)
                .execution_options(synchronize_session=False)
            )


async def log_call(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: int,
    thread_id: int | None,
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
                    thread_id=thread_id,
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
