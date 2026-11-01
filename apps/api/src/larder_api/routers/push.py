"""Reminders by Web Push: turn them on or off per browser, and the weekly recap on or off
(larder_api.reminders sends)."""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select

from larder_api.auth import CurrentUser
from larder_api.db import Session
from larder_api.demo import not_for_demo
from larder_api.schemas import (
    AheadSettingIn,
    PushConfigOut,
    PushSubscriptionIn,
    PushUnsubscribeIn,
    RecapSettingIn,
)
from larder_api.settings import Settings, get_settings
from larder_db.models import PushSubscription

router = APIRouter(prefix="/me/push", tags=["reminders"])

MAX_BROWSERS = 10
# The server POSTs to whatever endpoint is stored here, so an endpoint must be a browser's real
# push service: otherwise anyone could point this server at any address, inside or out.
PUSH_HOSTS = frozenset({"fcm.googleapis.com", "updates.push.services.mozilla.com"})
PUSH_DOMAINS = (".push.apple.com", ".push.services.mozilla.com", ".notify.windows.com")


def is_push_service(endpoint: str) -> bool:
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return (
        parts.scheme == "https"
        and port in (None, 443)
        and not (parts.username or parts.password)
        and (host in PUSH_HOSTS or host.endswith(PUSH_DOMAINS))
    )


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
        prep_reminders=user.prep_reminders,
    )


@router.put("/recap", status_code=status.HTTP_204_NO_CONTENT, operation_id="putRecapSetting")
async def put_recap(body: RecapSettingIn, user: CurrentUser, session: Session) -> Response:
    """The Sunday-evening recap on or off (in every browser with reminders on)."""
    user.weekly_recap = body.enabled
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/ahead", status_code=status.HTTP_204_NO_CONTENT, operation_id="putAheadSetting")
async def put_ahead(body: AheadSettingIn, user: CurrentUser, session: Session) -> Response:
    """The evening heads-up for tomorrow's meals (defrost, marinate) on or off."""
    user.prep_reminders = body.enabled
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="putPush",
    dependencies=[Depends(not_for_demo("Reminders"))],
)
async def subscribe(
    body: PushSubscriptionIn,
    user: CurrentUser,
    session: Session,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Send reminders to this browser (an endpoint moves to the user who subscribed last)."""
    if not (settings.vapid_public_key and settings.vapid_private_key):
        raise HTTPException(status.HTTP_409_CONFLICT, ["Reminders aren't set up on this server."])
    if not is_push_service(body.endpoint):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, ["Reminders don't work with this browser's push service."]
        )
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
