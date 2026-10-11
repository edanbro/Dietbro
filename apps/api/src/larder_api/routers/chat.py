"""Chat: send a message (streamed reply over SSE), read the current thread, start a new one.

Every query is filtered by the signed-in user; another user's thread id is a 404.
"""

from collections.abc import AsyncIterable, AsyncIterator
from datetime import datetime
from typing import Annotated, Any

from anyio.abc import ObjectReceiveStream
from fastapi import APIRouter, Depends, Query, status
from fastapi.sse import EventSourceResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api import planning
from larder_api.auth import CurrentUser
from larder_api.chat import gate, limits, service
from larder_api.chat.gate import PreparedTurn
from larder_api.chat.models import get_models
from larder_api.chat.scope import ChatScope, Emit, Models
from larder_api.chat.tasks import ChatTurns, get_chat_turns
from larder_api.clock import Clock, get_clock
from larder_api.db import FunctionSession, Session, get_sessionmaker
from larder_api.routers.plans import get_catalog_cache, get_replan_planner
from larder_api.schemas import ChatEvent, ChatMessageIn, ChatProblem, PendingTurn, ThreadOut
from larder_api.settings import Settings, get_settings
from larder_db import models as db

router = APIRouter(prefix="/chat", tags=["chat"])


def _problem(description: str) -> dict[str, Any]:
    return {"description": description, "model": ChatProblem}


_SEND_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: _problem("bad_today: `today` is implausible"),
    status.HTTP_404_NOT_FOUND: _problem("thread_not_found: no such thread (or not yours)"),
    status.HTTP_409_CONFLICT: _problem(
        "busy: still answering a message; duplicate: this client_id was already answered"
    ),
    status.HTTP_429_TOO_MANY_REQUESTS: _problem("daily_limit: try again at retry_at"),
}


async def prepare_turn(
    body: ChatMessageIn,
    user: CurrentUser,
    session: FunctionSession,
    models: Annotated[Models, Depends(get_models)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> PreparedTurn:
    """The gate (larder_api.chat.gate): raises the 4xx answers above as JSON ChatProblem."""
    return await gate.prepare(session, user.id, body, models, settings, clock())


async def start_turn(
    # Resolved before the gate, so a refusal here never leaves the turn lock taken.
    turns: Annotated[ChatTurns, Depends(get_chat_turns)],
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    catalog: Annotated[planning.CatalogCache, Depends(get_catalog_cache)],
    planner: Annotated[planning.Planner, Depends(get_replan_planner)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
    prepared: Annotated[PreparedTurn, Depends(prepare_turn)],
) -> AsyncIterator[ObjectReceiveStream[ChatEvent]]:
    """Start the detached turn before the response begins (a client that leaves at once still
    gets its reply stored); the stream of its events is closed when the response ends."""
    now = clock()

    def scope(emit: Emit) -> ChatScope:
        return service.make_scope(
            prepared,
            emit=emit,
            sessionmaker=sessionmaker,
            catalog=catalog,
            planner=planner,
            settings=settings,
            now=now,
        )

    events = turns.start(prepared, scope)
    async with events:
        yield events


async def _page(
    session: AsyncSession, thread_id: int, before_id: int | None, limit: int
) -> tuple[list[db.ChatMessage], bool]:
    """Up to `limit` messages before `before_id` (oldest first) and whether older ones exist."""
    query = select(db.ChatMessage).where(db.ChatMessage.thread_id == thread_id)
    if before_id is not None:
        query = query.where(db.ChatMessage.id < before_id)
    rows = list(await session.scalars(query.order_by(db.ChatMessage.id.desc()).limit(limit + 1)))
    return rows[:limit][::-1], len(rows) > limit


async def _thread_out(
    session: AsyncSession,
    user_id: int,
    thread_id: int | None,
    rows: list[db.ChatMessage],
    has_more: bool,
    models: Models,
    settings: Settings,
    now: datetime,
) -> ThreadOut:
    running = await limits.turn_in_progress(session, user_id, settings, now)
    pending = (
        PendingTurn(message_id=running[0], started_at=running[1])
        if running is not None and running[0] is not None
        else None
    )
    count, _ = await limits.messages_last_24h(session, user_id, now)
    if models.online:
        budget = await limits.budget(session, user_id, settings, now)
        available, reason, resets_at = budget.online, budget.reason, budget.resets_at
    else:
        available, reason, resets_at = False, models.offline_reason or "no_key", None
    return ThreadOut(
        thread_id=thread_id,
        messages=[service.message_out(row) for row in rows],
        has_more=has_more,
        pending=pending,
        llm_available=available,
        offline_reason=reason,
        llm_resets_at=resets_at,
        messages_today=count,
        daily_limit=settings.llm_daily_messages,
    )


@router.get("/thread", operation_id="getChatThread")
async def get_thread(
    user: CurrentUser,
    session: Session,
    models: Annotated[Models, Depends(get_models)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
    before_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ThreadOut:
    """The latest thread's messages (oldest first, `limit` before `before_id`), whether a reply
    is pending, and the user's model availability (key, budget) and message count."""
    thread = await gate.latest_thread(session, user.id)
    rows, has_more = (
        ([], False) if thread is None else await _page(session, thread.id, before_id, limit)
    )
    thread_id = thread.id if thread is not None else None
    return await _thread_out(session, user.id, thread_id, rows, has_more, models, settings, clock())


@router.post("/threads", status_code=status.HTTP_201_CREATED, operation_id="newChatThread")
async def new_thread(
    user: CurrentUser,
    session: Session,
    models: Annotated[Models, Depends(get_models)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ThreadOut:
    """Start a fresh conversation (earlier ones are kept for export)."""
    now = clock()
    thread = db.ChatThread(user_id=user.id, created_at=now, updated_at=now)
    session.add(thread)
    await session.commit()
    return await _thread_out(session, user.id, thread.id, [], False, models, settings, now)


@router.post(
    "/messages",
    response_class=EventSourceResponse,
    operation_id="sendChatMessage",
    responses=_SEND_ERRORS,
)
async def send_message(
    events: Annotated[ObjectReceiveStream[ChatEvent], Depends(start_turn)],
) -> AsyncIterable[ChatEvent]:
    """Stream the reply as server-sent events (each `data:` is one ChatEvent as JSON).

    The turn runs detached (larder_api.chat.tasks): this only relays its events, so a dropped
    connection doesn't stop the turn; the client reloads GET /chat/thread (pending) instead of
    resending."""
    # No request-scoped Session here: the gate and the turn open their own short sessions.
    async for event in events:
        yield event
