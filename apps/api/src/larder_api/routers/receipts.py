"""Receipt intake (M6): upload a photo or paste text, poll while the worker reads it, review
the suggested lines, confirm them into the pantry (docs/adr/0016-receipt-intake.md).

Status flow: queued -> processing -> ready | failed; ready -> confirmed. Every query is
filtered by the signed-in user; other users' uploads and lines are 404s.
"""

from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_api.auth import CurrentUser
from larder_api.clock import Clock, get_clock
from larder_api.db import Session
from larder_api.jobs import Enqueue, QueueUnavailable, get_enqueue
from larder_api.receipts import amount_for, confirm, item_of
from larder_api.routers.foods import summary
from larder_api.routers.pantry import out as pantry_out
from larder_api.routers.pantry import owned as owned_item
from larder_api.routers.pantry import to_grams
from larder_api.schemas import (
    Problems,
    ReceiptConfirmOut,
    ReceiptLineOut,
    ReceiptLinePatch,
    ReceiptOut,
    ReceiptSummary,
    ReceiptTextIn,
)
from larder_api.settings import Settings, get_settings
from larder_core.regions import local_today
from larder_core.shelf_life import suggest_expiry
from larder_db.models import Food, ReceiptLine, ReceiptUpload, User

router = APIRouter(prefix="/pantry/receipts", tags=["receipts"])

_PROBLEMS: dict[int | str, dict[str, Any]] = {status.HTTP_400_BAD_REQUEST: {"model": Problems}}
_UPLOAD_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_413_CONTENT_TOO_LARGE: {"description": "Photo over the size limit"},
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"description": "Not a JPEG, PNG or WebP photo"},
    status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Daily upload limit reached"},
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Job queue unavailable; try again"},
}
_HEIC_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1")


def sniff(data: bytes) -> str | None:
    """The photo's type from its first bytes (the client's Content-Type is not trusted)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        return "image/heic"
    return None


def line_out(line: ReceiptLine) -> ReceiptLineOut:
    return ReceiptLineOut(
        id=line.id,
        position=line.position,
        raw_text=line.raw_text,
        name=line.name,
        food=None if line.food is None else summary(line.food),
        match_method=line.match_method,
        quantity=line.quantity,
        unit=line.unit,
        grams=line.grams,
        approx=line.approx,
        price_minor=line.price_minor,
        expires_on=line.expires_on,
        status=line.status,  # pyright: ignore[reportArgumentType]
        pantry_item_id=line.pantry_item_id,
    )


def receipt_out(upload: ReceiptUpload) -> ReceiptOut:
    return ReceiptOut(
        id=upload.id,
        source=upload.source,  # pyright: ignore[reportArgumentType]
        status=upload.status,  # pyright: ignore[reportArgumentType]
        purchased_on=upload.purchased_on,
        error=upload.error,
        created_at=upload.created_at,
        processed_at=upload.processed_at,
        confirmed_at=upload.confirmed_at,
        lines=[line_out(line) for line in upload.lines],
    )


async def owned(session: AsyncSession, user: User, upload_id: int) -> ReceiptUpload:
    upload = await session.scalar(
        select(ReceiptUpload)
        .where(ReceiptUpload.id == upload_id, ReceiptUpload.user_id == user.id)
        .options(selectinload(ReceiptUpload.lines).joinedload(ReceiptLine.food))
        .execution_options(populate_existing=True)
    )
    if upload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "receipt not found")
    return upload


async def _check_quota(
    session: AsyncSession, user: User, settings: Settings, now: datetime
) -> None:
    recent = await session.scalar(
        select(func.count(ReceiptUpload.id)).where(
            ReceiptUpload.user_id == user.id,
            ReceiptUpload.created_at > now - timedelta(hours=24),
        )
    )
    if (recent or 0) >= settings.receipt_daily_uploads:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"You can add {settings.receipt_daily_uploads} receipts a day; try again tomorrow.",
        )


async def _enqueue(
    session: AsyncSession, enqueue: Enqueue, user: User, upload: ReceiptUpload
) -> ReceiptOut:
    """Commit the upload, hand it to the worker; if the queue is down, fail it (photo deleted)."""
    await session.commit()
    try:
        await enqueue(upload.id)
    except QueueUnavailable as exc:
        upload.status, upload.error, upload.image = "failed", "queue unavailable", None
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Can't read receipts right now; try again soon."
        ) from exc
    return receipt_out(await owned(session, user, upload.id))


@router.post(
    "/image",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="uploadReceiptImage",
    responses=_UPLOAD_ERRORS,
)
async def upload_image(
    file: Annotated[UploadFile, File(description="Photo of the receipt: JPEG, PNG or WebP")],
    user: CurrentUser,
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
    enqueue: Annotated[Enqueue, Depends(get_enqueue)],
    clock: Annotated[Clock, Depends(get_clock)],
    purchased_on: Annotated[date | None, Form()] = None,
) -> ReceiptOut:
    """Queue a receipt photo for reading. The photo is deleted as soon as it has been read."""
    data = await file.read(settings.receipt_max_image_bytes + 1)
    if len(data) > settings.receipt_max_image_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Photo is over {settings.receipt_max_image_bytes // 1_000_000} MB.",
        )
    kind = sniff(data)
    if kind == "image/heic":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "HEIC photos aren't supported yet: choose 'Most Compatible' (JPEG) or take a "
            "screenshot.",
        )
    if kind is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a JPEG, PNG or WebP.")
    now = clock()
    await _check_quota(session, user, settings, now)
    upload = ReceiptUpload(
        user_id=user.id,
        source="image",
        status="queued",
        purchased_on=purchased_on or local_today(user.timezone, now),
        image=data,
        image_type=kind,
        image_bytes=len(data),
    )
    session.add(upload)
    return await _enqueue(session, enqueue, user, upload)


@router.post(
    "/text",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="submitReceiptText",
    responses=_UPLOAD_ERRORS,
)
async def submit_text(
    body: ReceiptTextIn,
    user: CurrentUser,
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
    enqueue: Annotated[Enqueue, Depends(get_enqueue)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> ReceiptOut:
    """Queue pasted receipt text (e.g. from an online order) for reading."""
    now = clock()
    await _check_quota(session, user, settings, now)
    upload = ReceiptUpload(
        user_id=user.id,
        source="text",
        status="queued",
        purchased_on=body.purchased_on or local_today(user.timezone, now),
        text=body.text,
    )
    session.add(upload)
    return await _enqueue(session, enqueue, user, upload)


@router.get("", operation_id="listReceipts")
async def list_receipts(user: CurrentUser, session: Session) -> list[ReceiptSummary]:
    """The 20 most recent uploads, newest first."""
    counts = (
        select(ReceiptLine.upload_id, func.count(ReceiptLine.id).label("n"))
        .group_by(ReceiptLine.upload_id)
        .subquery()
    )
    rows = await session.execute(
        select(ReceiptUpload, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.upload_id == ReceiptUpload.id)
        .where(ReceiptUpload.user_id == user.id)
        .order_by(ReceiptUpload.created_at.desc(), ReceiptUpload.id.desc())
        .limit(20)
    )
    return [
        ReceiptSummary(
            id=u.id,
            source=u.source,  # pyright: ignore[reportArgumentType]
            status=u.status,  # pyright: ignore[reportArgumentType]
            purchased_on=u.purchased_on,
            error=u.error,
            created_at=u.created_at,
            lines=n,
        )
        for u, n in rows
    ]


@router.get("/{upload_id}", operation_id="getReceipt")
async def get_receipt(upload_id: int, user: CurrentUser, session: Session) -> ReceiptOut:
    return receipt_out(await owned(session, user, upload_id))


@router.patch("/{upload_id}/lines/{line_id}", operation_id="updateReceiptLine", responses=_PROBLEMS)
async def update_line(
    upload_id: int, line_id: int, body: ReceiptLinePatch, user: CurrentUser, session: Session
) -> ReceiptLineOut:
    """Edit a suggestion before confirming: food, quantity + unit, use-by date, or status."""
    upload = await owned(session, user, upload_id)
    line = next((x for x in upload.lines if x.id == line_id), None)
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "line not found")
    if upload.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, f"receipt is {upload.status}")
    changes = body.model_dump(exclude_unset=True)
    edited = False
    food = line.food
    if changes.get("food_id") is not None and changes["food_id"] != line.food_id:
        food = await session.get(Food, changes["food_id"])
        if food is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "food not found")
        line.food_id, line.food, line.match_method = food.id, food, "user"
        if "quantity" not in changes and "unit" not in changes:
            amount = await amount_for(session, item_of(line), food)
            line.quantity, line.unit, line.grams = amount.quantity, amount.unit, amount.grams
            line.approx = amount.approx
        if "expires_on" not in changes:
            line.expires_on = suggest_expiry(
                upload.purchased_on, food.description, food.category, storage=item_of(line).storage
            )
        edited = True
    if "quantity" in changes or "unit" in changes:
        if food is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, ["choose a food first"])
        quantity = body.quantity or line.quantity
        unit = body.unit or line.unit
        if quantity is None or unit is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, ["give both a quantity and a unit"])
        line.grams = await to_grams(session, food, quantity, unit)
        line.quantity, line.unit, line.approx = quantity, unit, False
        edited = True
    if "approx" in changes and body.approx is not None:
        line.approx = body.approx
        edited = True
    if "expires_on" in changes:
        line.expires_on = body.expires_on
        edited = True
    if body.status == "rejected":
        line.status = "rejected"
    elif body.status == "accepted" or (edited and body.status is None):
        if line.food_id is None or line.grams is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, ["choose a food first"])
        line.status = "edited" if edited else "accepted"
    elif body.status == "suggested":
        line.status = "edited" if edited else "suggested"
    await session.commit()
    upload = await owned(session, user, upload_id)
    return line_out(next(x for x in upload.lines if x.id == line_id))


@router.post("/{upload_id}/confirm", operation_id="confirmReceipt", responses=_PROBLEMS)
async def confirm_receipt(upload_id: int, user: CurrentUser, session: Session) -> ReceiptConfirmOut:
    """Add every line that isn't rejected and has a food to the pantry (source `receipt`,
    approximate where the size wasn't printed); suggested lines become accepted. Lines without
    a food are skipped. 409 unless the receipt is ready (so confirming twice adds nothing)."""
    upload = await owned(session, user, upload_id)
    if upload.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, f"receipt is {upload.status}")
    pairs = confirm(upload)
    session.add_all(item for _, item in pairs)
    await session.flush()
    for line, item in pairs:
        line.pantry_item_id = item.id
    await session.commit()
    created = [pantry_out(await owned_item(session, user, item.id)) for _, item in pairs]
    return ReceiptConfirmOut(
        receipt=receipt_out(await owned(session, user, upload_id)), created=created
    )


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteReceipt")
async def delete_receipt(upload_id: int, user: CurrentUser, session: Session) -> Response:
    """Delete the upload, its photo (if not yet read) and its lines. Pantry items already
    confirmed from it stay."""
    await session.delete(await owned(session, user, upload_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
