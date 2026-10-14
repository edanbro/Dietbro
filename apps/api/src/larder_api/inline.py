"""Background work inside the API process, for hosts without a separate worker (free tiers:
`WORKER_IN_API=true`). Instead of the arq worker on Redis:

- Pasted receipts are read in an asyncio task right after they're queued (the same
  `process_upload` the worker runs). Receipt photos are refused: OCR stays in the worker image.
- A minute ticker runs the periodic jobs: stale receipts every 5 minutes, expiry reminders on
  the hour, the demo account's reset at 03:00 UTC.

Nothing polls Redis, so a free Redis plan's command quota is left alone. On a host that sleeps
when idle, periodic jobs only run while it's awake (reminders may be missed then).
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api.demo import reset_demo
from larder_api.receipts import ReceiptUnreadable, process_upload, sweep_stale
from larder_api.reminders import send_due
from larder_api.settings import Settings

__all__ = ["NO_PHOTOS", "InlineWorker"]

logger = logging.getLogger(__name__)

NO_PHOTOS = (
    "Reading receipt photos isn't available on this server. Paste the receipt text instead "
    "(from an online order or email)."
)


class InlineWorker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessionmaker = sessionmaker
        self.settings = settings
        self.clock = clock
        self._tasks: set[asyncio.Task[object]] = set()
        self._ticker: asyncio.Task[None] | None = None

    def _spawn(self, work: Awaitable[object]) -> None:
        task: asyncio.Task[object] = asyncio.ensure_future(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def enqueue(self, upload_id: int) -> None:
        """The API's Enqueue: read the receipt in the background."""
        self._spawn(self._read(upload_id))

    async def _read(self, upload_id: int) -> None:
        async def no_photos(_data: bytes) -> str:
            raise ReceiptUnreadable(NO_PHOTOS)

        try:
            await process_upload(self.sessionmaker, upload_id, no_photos)
        except Exception:
            logger.exception("reading receipt %d failed", upload_id)

    async def tick(self, now: datetime) -> None:
        """The periodic jobs due at `now` (a minute boundary)."""
        if now.minute % 5 == 0:
            stale = timedelta(minutes=self.settings.receipt_stale_after_min)
            await sweep_stale(self.sessionmaker, stale)
        if now.minute == 0:
            sent = await send_due(self.sessionmaker, now, self.settings)
            if sent:
                logger.info("sent %d expiry reminders", sent)
        if self.settings.demo_auth_subject and now.hour == 3 and now.minute == 0:
            await reset_demo(self.sessionmaker, self.settings.demo_auth_subject, now)
            logger.info("demo account reset")

    async def _run(self) -> None:
        while True:
            now = self.clock()
            await asyncio.sleep(60 - now.second - now.microsecond / 1e6)
            try:
                await self.tick(self.clock().replace(second=0, microsecond=0))
            except Exception:
                logger.exception("periodic jobs failed")

    def start(self) -> None:
        self._ticker = asyncio.create_task(self._run())

    async def close(self) -> None:
        if self._ticker is not None:
            self._ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ticker
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=10)
