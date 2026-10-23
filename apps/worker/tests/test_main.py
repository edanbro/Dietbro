"""The arq worker's wiring: job names match what the API enqueues, and a photo that isn't one
fails with a message for the user (and is deleted)."""

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.jobs import READ_RECEIPT, RESET_DEMO, SEND_REMINDERS, SWEEP_RECEIPTS
from larder_db import models as db
from larder_db.engine import make_sessionmaker
from larder_worker.main import NOT_AN_IMAGE, WorkerSettings, read_receipt
from larder_worker.ocr import Ocr


def test_worker_runs_the_jobs_the_api_enqueues() -> None:
    assert [f.name for f in WorkerSettings.functions] == [READ_RECEIPT]
    crons = [c.name for c in WorkerSettings.cron_jobs]
    assert crons == [SWEEP_RECEIPTS, SEND_REMINDERS, RESET_DEMO]


async def test_a_file_that_is_not_an_image_fails_politely(db_engine: AsyncEngine) -> None:
    maker = make_sessionmaker(db_engine)
    async with maker() as session:
        user = db.User(auth_subject="worker-test")
        session.add(user)
        await session.flush()
        upload = db.ReceiptUpload(
            user_id=user.id,
            source="image",
            status="queued",
            purchased_on=date(2026, 10, 12),
            image=b"\x89PNG\r\n\x1a\n not really",
            image_type="image/png",
        )
        session.add(upload)
        await session.commit()
        upload_id = upload.id
    ctx: dict[str, Any] = {"maker": maker, "ocr": Ocr()}

    assert await read_receipt(ctx, upload_id) == "failed"

    async with maker() as session:
        row = (
            await session.execute(
                select(db.ReceiptUpload.error, db.ReceiptUpload.image).where(
                    db.ReceiptUpload.id == upload_id
                )
            )
        ).one()
        assert tuple(row) == (NOT_AN_IMAGE, None)
