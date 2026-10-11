"""Everything about a chat message that can fail runs here, as a dependency of
POST /chat/messages, so failures are real HTTP errors (inside the SSE generator they would
arrive as an empty 200 stream). In order, in one short transaction:

1. `today` within a day of the clock's UTC date, and not earlier than the `today` of the
   thread's previous user message -> else 400 bad_today.
2. thread: body.thread_id must be the user's (404 thread_not_found); omitted -> the latest
   thread, or a new one.
3. duplicate client_id for this user -> if its turn is still running, 409 busy with that
   message_id; if answered, 409 duplicate with the message id (the client then reloads the
   thread). No second turn either way.
4. turn lock (limits.acquire_turn with a fresh token) -> else 409 busy (+ the pending message id).
5. messages in the last 24 h >= llm_daily_messages -> release the lock, 429 daily_limit with
   retry_at.
6. mode: Models from get_models, then limits.budget -> online or offline (reason).
7. store the user's ChatMessage (text, client_id; api_messages filled by the turn), epoch =
   current epoch or a new one (last message older than chat_epoch_idle_min, or the epoch's
   stored api_messages estimated over chat_epoch_max_tokens at ~4 chars/token); set the lock's
   message id; commit.
Returns PreparedTurn; the turn task owns releasing the lock from here on.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from larder_api.chat import limits
from larder_api.chat.scope import Models
from larder_api.schemas import ChatMessageIn, ChatProblem
from larder_api.settings import Settings
from larder_db import models as db

CHARS_PER_TOKEN = 4
type Code = Literal["bad_today", "thread_not_found", "busy", "duplicate", "daily_limit"]


@dataclass(frozen=True, slots=True)
class PreparedTurn:
    user_id: int
    thread_id: int
    message_id: int
    epoch: int
    new_epoch: bool
    lock_token: uuid.UUID
    text: str
    today: date
    local_time: time | None
    models: Models  # chat=None when offline for this turn (models.offline_reason says why)
    turn_cap_micro_usd: int
    messages_today: int  # including this one


class ChatRefused(HTTPException):
    """A gate answer; sent as a JSON ChatProblem (see `problem_response`)."""

    def __init__(self, status_code: int, problem: ChatProblem) -> None:
        super().__init__(status_code, problem.detail)
        self.problem = problem


async def problem_response(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ChatRefused)
    return JSONResponse(exc.problem.model_dump(mode="json"), status_code=exc.status_code)


def _refuse(
    status_code: int,
    code: Code,
    detail: str,
    *,
    message_id: int | None = None,
    retry_at: datetime | None = None,
) -> ChatRefused:
    problem = ChatProblem(detail=[detail], code=code, message_id=message_id, retry_at=retry_at)
    return ChatRefused(status_code, problem)


BAD_TODAY = "Your device's date looks wrong - please check it and try again."
BUSY = "I'm still working on your last message."


async def prepare(
    session: AsyncSession,
    user_id: int,
    body: ChatMessageIn,
    models: Models,
    settings: Settings,
    now: datetime,
) -> PreparedTurn:
    """Run the gate for one message (see the module docstring); commits on success, rolls
    back (nothing stored, lock not taken) on any refusal."""
    try:
        return await _prepare(session, user_id, body, models, settings, now)
    except Exception:
        await session.rollback()
        raise


async def _prepare(
    session: AsyncSession,
    user_id: int,
    body: ChatMessageIn,
    models: Models,
    settings: Settings,
    now: datetime,
) -> PreparedTurn:
    if abs((body.today - now.astimezone(UTC).date()).days) > 1:
        raise _refuse(status.HTTP_400_BAD_REQUEST, "bad_today", BAD_TODAY)
    thread, is_new = await _thread(session, user_id, body.thread_id)
    if not is_new:
        previous = await session.scalar(
            select(db.ChatMessage.today)
            .where(db.ChatMessage.thread_id == thread.id, db.ChatMessage.role == "user")
            .order_by(db.ChatMessage.id.desc())
            .limit(1)
        )
        if previous is not None and body.today < previous:
            raise _refuse(status.HTTP_400_BAD_REQUEST, "bad_today", BAD_TODAY)

    seen = await session.scalar(
        select(db.ChatMessage.id).where(
            db.ChatMessage.user_id == user_id, db.ChatMessage.client_id == body.client_id
        )
    )
    if seen is not None:
        running = await limits.turn_in_progress(session, user_id, settings, now)
        if running is not None and running[0] == seen:
            raise _refuse(status.HTTP_409_CONFLICT, "busy", BUSY, message_id=seen)
        raise _refuse(
            status.HTTP_409_CONFLICT,
            "duplicate",
            "That message was already answered.",
            message_id=seen,
        )

    token = uuid.uuid4()
    if not await limits.acquire_turn(session, user_id, token, settings, now):
        running = await limits.turn_in_progress(session, user_id, settings, now)
        pending = running[0] if running else None
        raise _refuse(status.HTTP_409_CONFLICT, "busy", BUSY, message_id=pending)

    count, retry_at = await limits.messages_last_24h(session, user_id, now)
    if count >= settings.llm_daily_messages:
        raise _refuse(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "daily_limit",
            f"You've sent {settings.llm_daily_messages} messages in the last 24 hours. "
            "Please try again later.",
            retry_at=retry_at,
        )

    turn_cap = 0
    if models.online:
        budget = await limits.budget(session, user_id, settings, now)
        turn_cap = budget.turn_cap_micro_usd
        if not budget.online:
            models = Models(offline_reason=budget.reason)

    if is_new:
        session.add(thread)
        await session.flush()
    epoch, new_epoch = await _epoch(session, thread.id, settings, now)
    message = db.ChatMessage(
        thread_id=thread.id,
        user_id=user_id,
        role="user",
        client_id=body.client_id,
        today=body.today,
        text=body.text,
        api_messages=[],
        api_epoch=epoch,
        created_at=now,
    )
    session.add(message)
    thread.updated_at = now
    await session.flush()
    await limits.set_turn_message(session, user_id, token, message.id)
    await session.commit()
    return PreparedTurn(
        user_id=user_id,
        thread_id=thread.id,
        message_id=message.id,
        epoch=epoch,
        new_epoch=new_epoch,
        lock_token=token,
        text=body.text,
        today=body.today,
        local_time=body.local_time,
        models=models,
        turn_cap_micro_usd=turn_cap,
        messages_today=count + 1,
    )


async def latest_thread(session: AsyncSession, user_id: int) -> db.ChatThread | None:
    """The thread the client shows: the one started last ("new chat" makes a new one current,
    and a late reply in an older thread doesn't bring that one back)."""
    return await session.scalar(
        select(db.ChatThread)
        .where(db.ChatThread.user_id == user_id)
        .order_by(db.ChatThread.id.desc())
        .limit(1)
    )


async def _thread(
    session: AsyncSession, user_id: int, thread_id: int | None
) -> tuple[db.ChatThread, bool]:
    """(the named thread (the user's), else the latest, else a new unsaved one; whether new)."""
    if thread_id is not None:
        thread = await session.scalar(
            select(db.ChatThread).where(
                db.ChatThread.user_id == user_id, db.ChatThread.id == thread_id
            )
        )
        if thread is None:
            raise _refuse(
                status.HTTP_404_NOT_FOUND, "thread_not_found", "That conversation doesn't exist."
            )
        return thread, False
    latest = await latest_thread(session, user_id)
    return (latest, False) if latest else (db.ChatThread(user_id=user_id), True)


async def _epoch(
    session: AsyncSession, thread_id: int, settings: Settings, now: datetime
) -> tuple[int, bool]:
    """(epoch for the new message, whether it starts a fresh transcript)."""
    last = (
        await session.execute(
            select(db.ChatMessage.api_epoch, db.ChatMessage.created_at)
            .where(db.ChatMessage.thread_id == thread_id)
            .order_by(db.ChatMessage.id.desc())
            .limit(1)
        )
    ).one_or_none()
    if last is None:
        return 0, True
    epoch, last_at = last
    if now - last_at > timedelta(minutes=settings.chat_epoch_idle_min):
        return epoch + 1, True
    size = await session.scalar(
        select(
            func.coalesce(func.sum(func.length(cast(db.ChatMessage.api_messages, Text))), 0)
        ).where(db.ChatMessage.thread_id == thread_id, db.ChatMessage.api_epoch == epoch)
    )
    if (size or 0) / CHARS_PER_TOKEN > settings.chat_epoch_max_tokens:
        return epoch + 1, True
    return epoch, False
