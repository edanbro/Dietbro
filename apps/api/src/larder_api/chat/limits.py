"""Per-user LLM limits (settings.llm_daily_messages, llm_monthly_cap_usd) and call logging.

- Daily messages: the user's chat messages (role=user) since 00:00 UTC. At the limit the chat
  endpoint answers HTTP 429 before streaming, with a message saying when it resets.
- Monthly cost: sum of llm_calls.cost_micro_usd since the 1st (UTC). At or over the cap the turn
  runs offline (same plan changes, templated reply) and says so once in the reply.
- One turn at a time per user: a Redis lock `chat:{user_id}` (SET NX, 120 s TTL), else 409.
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from larder_db import models as db
from larder_llm.client import ModelCall


async def messages_today(session: AsyncSession, user_id: int) -> int:
    raise NotImplementedError


async def spent_this_month_micro_usd(session: AsyncSession, user_id: int) -> int:
    raise NotImplementedError


def log_calls(
    session: AsyncSession, user_id: int, thread_id: int | None, calls: Sequence[ModelCall]
) -> list[db.LlmCall]:
    """Add one llm_calls row per call, priced with larder_llm.pricing.cost_micro_usd."""
    raise NotImplementedError
