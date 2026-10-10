"""Chat: send a message (streamed reply over SSE), read the current thread, start a new one.

Every query is filtered by the signed-in user; another user's thread id is a 404.
"""

from collections.abc import AsyncIterable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.sse import EventSourceResponse

from larder_api.auth import CurrentUser
from larder_api.chat.models import get_models
from larder_api.chat.scope import Models
from larder_api.db import Session
from larder_api.schemas import ChatEvent, ChatMessageIn, Problems, ThreadOut
from larder_api.settings import Settings, get_settings

router = APIRouter(prefix="/chat", tags=["chat"])

_SEND_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: {"model": Problems, "description": "`today` is implausible"},
    status.HTTP_404_NOT_FOUND: {"description": "no such thread (or not yours)"},
    status.HTTP_409_CONFLICT: {
        "model": Problems,
        "description": "still answering your previous message, or setup incomplete",
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": Problems,
        "description": "daily message limit reached",
    },
}


@router.get("/thread", operation_id="getChatThread")
async def get_thread(
    user: CurrentUser,
    session: Session,
    models: Annotated[Models, Depends(get_models)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ThreadOut:
    """The latest thread's messages (oldest first), or an empty thread if there is none."""
    raise NotImplementedError


@router.post("/threads", status_code=status.HTTP_201_CREATED, operation_id="newChatThread")
async def new_thread(
    user: CurrentUser,
    session: Session,
    models: Annotated[Models, Depends(get_models)],
    settings: Annotated[Settings, Depends(get_settings)],
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
    body: ChatMessageIn,
    user: CurrentUser,
    session: Session,
    models: Annotated[Models, Depends(get_models)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterable[ChatEvent]:
    """Stream the reply as server-sent events (each `data:` is one ChatEvent as JSON).

    Checks that can fail run before the stream starts and are plain HTTP errors: daily limit
    (429), one turn at a time per user (409), thread ownership (404), `today` within a day of
    the server's UTC date (400). The turn itself (larder_api.chat.service.run_turn) opens its own
    database sessions: the request session is not used after streaming begins."""
    raise NotImplementedError
    yield  # pragma: no cover
