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
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api.settings import Settings
from larder_llm.client import ModelCall
from larder_llm.reply import OfflineReason


@dataclass(frozen=True, slots=True)
class Budget:
    online: bool
    reason: OfflineReason | None  # None when online
    resets_at: datetime | None
    turn_cap_micro_usd: int  # min(llm_turn_cap, what pacing allows today)


async def messages_last_24h(
    session: AsyncSession, user_id: int, now: datetime
) -> tuple[int, datetime | None]:
    """(count, when the oldest counted message turns 24 h old)."""
    raise NotImplementedError


async def budget(session: AsyncSession, user_id: int, settings: Settings, now: datetime) -> Budget:
    raise NotImplementedError


async def acquire_turn(
    session: AsyncSession, user_id: int, token: uuid.UUID, settings: Settings, now: datetime
) -> bool:
    raise NotImplementedError


async def set_turn_message(session: AsyncSession, user_id: int, token: uuid.UUID, mid: int) -> None:
    raise NotImplementedError


async def release_turn(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int, token: uuid.UUID
) -> None:
    raise NotImplementedError


async def log_call(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: int,
    thread_id: int | None,
    call: ModelCall,
) -> int:
    """Insert the llm_calls row; returns its cost in micro-dollars."""
    raise NotImplementedError
