"""Background work inside the API process, for hosts without a separate worker (free tiers:
`WORKER_IN_API=true`). Instead of the arq worker on Redis:

- Pasted receipts are read in an asyncio task right after they're queued (the same
  `process_upload` the worker runs). Receipt photos are refused: OCR stays in the worker image.
- A minute ticker runs the periodic jobs: stale receipts every 5 minutes, expiry reminders on
  the hour, and the demo account's reset, due at 03:00 UTC and caught up on waking: a free host
  is seldom awake at that minute. On waking it's the first thing done, ahead of the visitor who
  woke the server, so it doesn't wipe the plan they've just made.

Nothing polls Redis, so a free Redis plan's command quota is left alone. On a host that sleeps
when idle, periodic jobs only run while it's awake (reminders may be missed then).
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from larder_api.demo import last_reset_time, reset_if_stale
from larder_api.receipts import ReceiptUnreadable, process_upload, sweep_stale
from larder_api.reminders import send_ahead, send_due, send_recaps
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
        self._demo_checked: datetime | None = None

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

    async def _reset_demo(self, now: datetime) -> None:
        """Look at most once per reset time, so a quiet server's database can go to sleep."""
        subject = self.settings.demo_auth_subject
        due = last_reset_time(now)
        if subject and self._demo_checked != due:
            if await reset_if_stale(self.sessionmaker, subject, now):
                logger.info("demo account reset")
            self._demo_checked = due

    async def tick(self, now: datetime) -> None:
        """The periodic jobs due at `now` (a minute boundary)."""
        if now.minute % 5 == 0:
            stale = timedelta(minutes=self.settings.receipt_stale_after_min)
            await sweep_stale(self.sessionmaker, stale)
        if now.minute == 0:
            sent = await send_due(self.sessionmaker, now, self.settings)
            if sent:
                logger.info("sent %d expiry reminders", sent)
            recaps = await send_recaps(self.sessionmaker, now, self.settings)
            if recaps:
                logger.info("sent %d weekly recaps", recaps)
            ahead = await send_ahead(self.sessionmaker, now, self.settings)
            if ahead:
                logger.info("sent %d prep-ahead reminders", ahead)
        await self._reset_demo(now)

    async def _run(self) -> None:
        try:
            await self._reset_demo(self.clock())
        except Exception:
            logger.exception("demo account reset failed")
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
