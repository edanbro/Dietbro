"""Background jobs the API hands to the worker (apps/worker, arq on Redis).

The API only enqueues: `read_receipt(upload_id)` is run by the worker, which owns OCR. Job ids
are derived from the upload (`receipt:<id>`), so enqueueing the same upload twice is a no-op
while the first is queued or kept as a result; the job itself is idempotent anyway
(larder_api.receipts.process_upload).
"""

from collections.abc import Awaitable, Callable
from typing import cast

from arq.connections import ArqRedis
from fastapi import Request

READ_RECEIPT = "read_receipt"
SWEEP_RECEIPTS = "sweep_receipts"
SEND_REMINDERS = "send_reminders"

type Enqueue = Callable[[int], Awaitable[None]]


class QueueUnavailable(Exception):
    """Redis refused the job; the upload is marked failed and the client told to retry."""


def make_queue(redis_url: str) -> ArqRedis:
    """An arq client that connects on first use (the API starts with Redis down)."""
    return cast(ArqRedis, ArqRedis.from_url(redis_url))  # pyright: ignore[reportUnknownMemberType]


def job_id(upload_id: int) -> str:
    return f"receipt:{upload_id}"


def get_enqueue(request: Request) -> Enqueue:
    queue = cast(ArqRedis, request.app.state.queue)

    async def enqueue(upload_id: int) -> None:
        try:
            await queue.enqueue_job(READ_RECEIPT, upload_id, _job_id=job_id(upload_id))
        except Exception as exc:  # connection refused, timeout, ...
            raise QueueUnavailable(str(exc)) from exc

    return enqueue
