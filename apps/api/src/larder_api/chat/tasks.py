"""Chat turns run detached from the HTTP connection.

`ChatTurns` lives on app.state (created in the lifespan): `start(prepared, scope_factory)`
starts `service.run_turn` as a task in a long-lived anyio task group and returns an
`anyio.abc.ObjectReceiveStream` of ChatEvents (buffer large enough that a slow phone never
back-pressures the model stream; text deltas may be coalesced). The SSE endpoint only relays
that stream; when the client disconnects, the relay stops and the turn carries on, persists its
reply and releases the turn lock. Sends to a closed stream are ignored. Each turn runs under
`anyio.fail_after(chat_turn_deadline_s)`; lifespan shutdown waits for running turns up to that
deadline, then cancels them (their `finally` still releases the lock, shielded). Nothing a
turn raises leaves its task (a failed lock release is logged; the lock goes stale); should the
group die anyway, it stops accepting turns (503).

The task group is hosted by a task of its own (`open` / `close`, or `async with`), so whoever
opens it - the app lifespan, or a test fixture - may close it from another task.
"""

import asyncio
import contextlib
import logging
import math
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from typing import Self, cast

import anyio
from anyio.abc import ObjectReceiveStream, TaskGroup
from anyio.streams.memory import MemoryObjectSendStream
from fastapi import HTTPException, Request, status

from larder_api.chat import limits, service
from larder_api.chat.gate import PreparedTurn
from larder_api.chat.scope import ChatScope, Emit
from larder_api.schemas import ChatEvent, DoneEvent, ErrorEvent

logger = logging.getLogger(__name__)

type ScopeFactory = Callable[[Emit], ChatScope]

TIMED_OUT = "That took too long, sorry. Anything I changed is in your plan - please try again."


class ChatTurns:
    """The process's running chat turns (one task group), each under `deadline_s`."""

    def __init__(self, deadline_s: float) -> None:
        self.deadline_s = deadline_s
        self.running = 0  # turns started and not finished
        self._tg: TaskGroup | None = None
        self._host: asyncio.Task[None] | None = None
        self._stop: anyio.Event | None = None
        self._idle: anyio.Event | None = None  # set when the last running turn ends (shutdown)

    async def open(self) -> None:
        ready, self._stop = anyio.Event(), anyio.Event()
        self._host = asyncio.create_task(self._serve(ready, self._stop))
        await ready.wait()

    async def close(self) -> None:
        """Wait for running turns (up to the turn deadline), then cancel what's left."""
        if self._host is None or self._stop is None:
            return
        self._stop.set()
        await self._host
        self._host = None

    @property
    def accepting(self) -> bool:
        return self._tg is not None

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def _serve(self, ready: anyio.Event, stop: anyio.Event) -> None:
        try:
            async with anyio.create_task_group() as tg:
                self._tg = tg
                ready.set()
                await stop.wait()
                self._tg = None  # no new turns from here on
                self._idle = anyio.Event()
                if self.running:
                    with anyio.move_on_after(self.deadline_s):
                        await self._idle.wait()
                tg.cancel_scope.cancel()
        finally:
            self._tg = None  # a group that died takes no more turns (503, not 500)

    def start(
        self, prepared: PreparedTurn, scope_factory: ScopeFactory
    ) -> ObjectReceiveStream[ChatEvent]:
        if self._tg is None:
            raise RuntimeError("chat turns are not running")
        send, receive = anyio.create_memory_object_stream[ChatEvent](max_buffer_size=math.inf)
        self.running += 1
        self._tg.start_soon(self._run, prepared, scope_factory, send)
        return receive

    async def _run(
        self,
        prepared: PreparedTurn,
        scope_factory: ScopeFactory,
        send: MemoryObjectSendStream[ChatEvent],
    ) -> None:
        ended = False  # run_turn sent its done / error (and released the lock first)

        async def emit(event: object) -> None:
            with contextlib.suppress(anyio.BrokenResourceError, anyio.ClosedResourceError):
                send.send_nowait(cast(ChatEvent, event))

        scope: ChatScope | None = None
        try:
            with send:
                try:
                    with anyio.fail_after(self.deadline_s):
                        scope = scope_factory(emit)
                        turn = cast(AsyncGenerator[ChatEvent], service.run_turn(prepared, scope))
                        async with aclosing(turn) as events:
                            async for event in events:
                                ended = isinstance(event, DoneEvent | ErrorEvent)
                                await emit(event)
                except TimeoutError:
                    logger.warning("chat turn for message %s timed out", prepared.message_id)
                    await emit(ErrorEvent(message=TIMED_OUT))
                except Exception:
                    logger.exception("chat turn for message %s crashed", prepared.message_id)
                    await emit(ErrorEvent(message=service.FAILED))
        finally:
            self.running -= 1
            if not self.running and self._idle is not None:
                self._idle.set()
            if not ended and scope is not None:  # e.g. cancelled before run_turn started
                await _release(scope, prepared)


async def _release(scope: ChatScope, prepared: PreparedTurn) -> None:
    """Free the turn lock; a failure is logged, never raised (it would take the task group,
    and every other user's turn, down with it). The lock then goes stale after the deadline."""
    try:
        await limits.release_turn(scope.sessionmaker, prepared.user_id, prepared.lock_token)
    except Exception:
        logger.exception("couldn't release the turn lock for message %s", prepared.message_id)


def get_chat_turns(request: Request) -> ChatTurns:
    """Resolved before the gate: a server that is shutting down takes no new turns."""
    turns: ChatTurns | None = getattr(request.app.state, "chat_turns", None)
    if turns is None or not turns.accepting:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "chat is not running")
    return turns
