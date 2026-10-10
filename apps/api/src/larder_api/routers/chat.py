"""Chat: send a message (streamed reply over SSE), read the current thread, start a new one.

Every query is filtered by the signed-in user; another user's thread id is a 404.
"""

from collections.abc import AsyncIterable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.sse import EventSourceResponse

from larder_api.auth import CurrentUser
from larder_api.chat.gate import PreparedTurn
from larder_api.chat.models import get_models
from larder_api.chat.scope import Models
from larder_api.clock import Clock, get_clock
from larder_api.db import FunctionSession, Session
from larder_api.schemas import ChatEvent, ChatMessageIn, ChatProblem, ThreadOut
from larder_api.settings import Settings, get_settings

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
    raise NotImplementedError


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
    raise NotImplementedError


@router.post("/threads", status_code=status.HTTP_201_CREATED, operation_id="newChatThread")
async def new_thread(
    user: CurrentUser,
    session: Session,
    models: Annotated[Models, Depends(get_models)],
    settings: Annotated[Settings, Depends(get_settings)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ThreadOut:
    """Start a fresh conversation (earlier ones are kept for export)."""
    raise NotImplementedError


@router.post(
    "/messages",
    response_class=EventSourceResponse,
    operation_id="sendChatMessage",
    responses=_SEND_ERRORS,
)
async def send_message(
    prepared: Annotated[PreparedTurn, Depends(prepare_turn)],
) -> AsyncIterable[ChatEvent]:
    """Stream the reply as server-sent events (each `data:` is one ChatEvent as JSON).

    The turn runs detached (larder_api.chat.tasks): this only relays its events, so a dropped
    connection doesn't stop the turn; the client reloads GET /chat/thread (pending) instead of
    resending. Takes no request-scoped Session: the turn opens its own short sessions. The turn
    needs the sessionmaker, catalog cache, planner, settings and clock as dependencies too
    (add them here when implementing; tests override them)."""
    raise NotImplementedError
    yield  # pragma: no cover
