"""The arq worker: `arq larder_worker.main.WorkerSettings` (compose service `worker`).

Jobs (names in larder_api.jobs):
- read_receipt(upload_id): OCR the photo (in a thread; CPU-bound) or take the pasted text,
  then larder_api.receipts.process_upload parses, matches and writes the lines. Idempotent;
  retried once if the worker dies mid-job; failures are recorded on the upload.
- sweep_receipts (cron, every 5 min): fail uploads stuck queued/processing past
  receipt_stale_after_min (e.g. a job killed by its timeout) and delete their photos.

Settings come from the same environment as the API (larder_api.settings).
"""

import asyncio
import logging
from datetime import timedelta
from typing import Any, ClassVar

from arq import cron, func
from arq.connections import RedisSettings
from arq.typing import WorkerCoroutine

from larder_api.jobs import READ_RECEIPT, SWEEP_RECEIPTS
from larder_api.receipts import ReceiptUnreadable, process_upload, sweep_stale
from larder_api.settings import get_settings
from larder_db.engine import make_engine, make_sessionmaker
from larder_worker.ocr import Ocr, UnreadableImage

logger = logging.getLogger(__name__)
settings = get_settings()

NOT_AN_IMAGE = "Couldn't open the photo. Upload a JPEG, PNG or WebP picture of the receipt."


async def startup(ctx: dict[str, Any]) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    for name in ("larder_api", "larder_worker"):  # arq configures its own logger
        logging.getLogger(name).addHandler(handler)
        logging.getLogger(name).setLevel(logging.INFO)
    engine = make_engine(settings.database_url, pool_pre_ping=True)
    ctx["engine"] = engine
    ctx["maker"] = make_sessionmaker(engine)
    ocr = Ocr(settings.ocr_max_side_px)
    ctx["ocr"] = ocr
    await asyncio.to_thread(ocr.engine)  # load the models now, not on the first receipt


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


async def read_receipt(ctx: dict[str, Any], upload_id: int) -> str | None:
    ocr: Ocr = ctx["ocr"]

    async def read_image(data: bytes) -> str:
        try:
            return await asyncio.to_thread(ocr.read, data)
        except UnreadableImage as exc:
            raise ReceiptUnreadable(NOT_AN_IMAGE) from exc

    return await process_upload(ctx["maker"], upload_id, read_image)


async def sweep_receipts(ctx: dict[str, Any]) -> int:
    swept = await sweep_stale(ctx["maker"], timedelta(minutes=settings.receipt_stale_after_min))
    if swept:
        logger.warning("marked %d stale receipt uploads failed", swept)
    return swept


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        func(
            read_receipt,  # pyright: ignore[reportArgumentType]
            name=READ_RECEIPT,
            timeout=settings.receipt_job_timeout_s,
            max_tries=2,
        )
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(
            sweep_receipts,  # pyright: ignore[reportArgumentType]
            name=SWEEP_RECEIPTS,
            minute=set(range(0, 60, 5)),
            run_at_startup=True,
        )
    ]
    on_startup: ClassVar[WorkerCoroutine] = startup  # pyright: ignore[reportAssignmentType]
    on_shutdown: ClassVar[WorkerCoroutine] = shutdown  # pyright: ignore[reportAssignmentType]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 2  # OCR is CPU-bound; more jobs only queue on the cores
    keep_result = 3600
    health_check_interval = 30
