"""Compose smoke test for receipt intake (CI): `docker compose exec worker python -m
larder_worker.smoke`.

Through the real queue and the running worker: a pasted receipt and a photo (rendered here with
Pillow's built-in font) are enqueued for a throwaway user, and each must come back `ready` with
its item line read; the photo must be gone from the database. The user (and so the uploads) is
deleted at the end. Exits non-zero on failure. Needs migrations, not seeded foods (lines may
stay unmatched).
"""

import asyncio
import sys
import uuid
from datetime import date
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import delete, select

from larder_api.jobs import READ_RECEIPT, job_id, make_queue
from larder_api.settings import get_settings
from larder_db.engine import make_engine, make_sessionmaker
from larder_db.models import ReceiptLine, ReceiptUpload, User

TEXT = "SMOKE MART\nSEMI SKMD MILK 4PT    1.45\nTOTAL    1.45\nVISA    1.45\n"


def photo() -> bytes:
    font = ImageFont.load_default(size=32)
    image = Image.new("RGB", (900, 260), "white")
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(TEXT.splitlines()):
        draw.text((40, 30 + i * 52), line, font=font, fill="black")
    out = BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()


async def run(timeout_s: float = 90) -> list[str]:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    maker = make_sessionmaker(engine)
    queue = make_queue(settings.redis_url)
    problems: list[str] = []
    try:
        async with maker() as session:
            user = User(auth_subject=f"smoke-{uuid.uuid4()}")
            session.add(user)
            await session.flush()
            uploads = [
                ReceiptUpload(
                    user_id=user.id,
                    source="text",
                    status="queued",
                    purchased_on=date.today(),
                    text=TEXT,
                ),
                ReceiptUpload(
                    user_id=user.id,
                    source="image",
                    status="queued",
                    purchased_on=date.today(),
                    image=photo(),
                    image_type="image/jpeg",
                ),
            ]
            session.add_all(uploads)
            await session.commit()
            ids = [u.id for u in uploads]
            user_id = user.id
        for upload_id in ids:
            await queue.enqueue_job(READ_RECEIPT, upload_id, _job_id=job_id(upload_id))

        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            async with maker() as session:
                rows = (
                    await session.execute(
                        select(
                            ReceiptUpload.id,
                            ReceiptUpload.source,
                            ReceiptUpload.status,
                            ReceiptUpload.error,
                            ReceiptUpload.image.is_(None),
                        ).where(ReceiptUpload.id.in_(ids))
                    )
                ).all()
                lines = (
                    await session.scalars(
                        select(ReceiptLine.raw_text).where(ReceiptLine.upload_id.in_(ids))
                    )
                ).all()
            if all(r.status not in ("queued", "processing") for r in rows):
                break
            if asyncio.get_running_loop().time() > deadline:
                problems.append(f"timed out: {[(r.source, r.status) for r in rows]}")
                break
            await asyncio.sleep(1)
        for r in rows:
            print(f"{r.source}: {r.status} {r.error or ''}")
            if r.status != "ready":
                problems.append(f"{r.source} upload is {r.status}: {r.error}")
            if not r[4]:
                problems.append(f"{r.source} upload still holds a photo")
        print("lines:", list(lines))
        if sum("MILK" in line.upper() for line in lines) != 2:
            problems.append(f"expected the milk line from both uploads, got {list(lines)}")
        async with maker() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
    finally:
        await queue.aclose()
        await engine.dispose()
    return problems


def main() -> None:
    problems = asyncio.run(run())
    for p in problems:
        print("FAIL:", p, file=sys.stderr)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
