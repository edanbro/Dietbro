"""Reminders by Web Push: turn them on or off per browser, and the weekly recap on or off
(larder_api.reminders sends)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select

from larder_api.auth import CurrentUser
from larder_api.db import Session
from larder_api.schemas import (
    PushConfigOut,
    PushSubscriptionIn,
    PushUnsubscribeIn,
    RecapSettingIn,
)
from larder_api.settings import Settings, get_settings
from larder_db.models import PushSubscription

router = APIRouter(prefix="/me/push", tags=["reminders"])

MAX_BROWSERS = 10


@router.get("", operation_id="getPush")
async def get_push(
    user: CurrentUser, session: Session, settings: Annotated[Settings, Depends(get_settings)]
) -> PushConfigOut:
    enabled = bool(settings.vapid_public_key and settings.vapid_private_key)
    count = await session.scalar(
        select(func.count(PushSubscription.id)).where(PushSubscription.user_id == user.id)
    )
    return PushConfigOut(
        enabled=enabled,
        public_key=settings.vapid_public_key if enabled else None,
        subscribed=count or 0,
        weekly_recap=user.weekly_recap,
    )


@router.put("/recap", status_code=status.HTTP_204_NO_CONTENT, operation_id="putRecapSetting")
async def put_recap(body: RecapSettingIn, user: CurrentUser, session: Session) -> Response:
    """The Sunday-evening recap on or off (in every browser with reminders on)."""
    user.weekly_recap = body.enabled
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("", status_code=status.HTTP_204_NO_CONTENT, operation_id="putPush")
async def subscribe(
    body: PushSubscriptionIn,
    user: CurrentUser,
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Send reminders to this browser (an endpoint moves to the user who subscribed last)."""
    if not (settings.vapid_public_key and settings.vapid_private_key):
        raise HTTPException(status.HTTP_409_CONFLICT, ["Reminders aren't set up on this server."])
    row = await session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    if row is None:
        count = await session.scalar(
            select(func.count(PushSubscription.id)).where(PushSubscription.user_id == user.id)
        )
        if (count or 0) >= MAX_BROWSERS:
            raise HTTPException(
                status.HTTP_409_CONFLICT, ["Reminders are on in too many browsers already."]
            )
        row = PushSubscription(endpoint=body.endpoint)
        session.add(row)
    row.user_id = user.id
    row.p256dh, row.auth = body.keys.p256dh, body.keys.auth
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT, operation_id="deletePush")
async def unsubscribe(body: PushUnsubscribeIn, user: CurrentUser, session: Session) -> Response:
    await session.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user.id, PushSubscription.endpoint == body.endpoint
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
