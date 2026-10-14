"""Expiry reminders by Web Push (larder_api.reminders) and the /me/push routes."""

import base64
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from larder_api.main import app
from larder_api.reminders import Gone, Reminder, generate_vapid_keys, reminder_for, send_due
from larder_api.settings import Settings, get_settings
from larder_db.engine import make_sessionmaker
from larder_db.models import PantryItem, PushSubscription, User

Auth = Callable[..., dict[str, str]]
NewUser = Callable[..., Awaitable[int]]

ONION, OLIVE_OIL = 170000, 171413  # seeded by the `foods` fixture
TODAY = date(2026, 10, 14)
# 08:00 UTC is 09:00 in Dublin (Irish summer time until 25 October).
NINE_IN_DUBLIN = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
KEYS = generate_vapid_keys()
SETTINGS = Settings.model_validate(
    {"vapid_public_key": KEYS[0], "vapid_private_key": KEYS[1], "reminder_hour": 9}
)


# Explicit: a developer's .env may hold real keys.
NO_KEYS = Settings.model_validate({"vapid_public_key": None, "vapid_private_key": None})


@pytest.fixture
def push_enabled() -> Iterator[None]:
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    yield
    app.dependency_overrides.pop(get_settings, None)


async def setup_user(engine: AsyncEngine, new_user: NewUser, *expiring: tuple[int, date]) -> int:
    uid = await new_user("user_a")
    async with make_sessionmaker(engine)() as session:
        await session.execute(update(User).where(User.id == uid).values(timezone="Europe/Dublin"))
        for food_id, expires in expiring:
            session.add(
                PantryItem(
                    user_id=uid,
                    food_id=food_id,
                    grams=500,
                    quantity=500,
                    unit="g",
                    expires_on=expires,
                    source="manual",
                )
            )
        session.add(
            PushSubscription(
                user_id=uid, endpoint="https://push.example/1", p256dh="p" * 20, auth="a" * 16
            )
        )
        await session.commit()
    return uid


class FakePush:
    def __init__(self, gone: bool = False) -> None:
        self.sent: list[tuple[str, Reminder]] = []
        self.gone = gone

    async def __call__(self, sub: PushSubscription, reminder: Reminder) -> None:
        if self.gone:
            raise Gone
        self.sent.append((sub.endpoint, reminder))


def pad(text: str) -> str:
    return text + "=" * (-len(text) % 4)


def test_vapid_keys_are_browser_ready() -> None:
    public, private = generate_vapid_keys()
    raw_public = base64.urlsafe_b64decode(pad(public))
    assert len(raw_public) == 65  # uncompressed P-256 point
    assert raw_public[0] == 4
    assert len(base64.urlsafe_b64decode(pad(private))) == 32


@pytest.mark.usefixtures("foods")
async def test_reminder_names_food_expiring_today_and_tomorrow(
    db_engine: AsyncEngine, new_user: NewUser
) -> None:
    uid = await setup_user(
        db_engine,
        new_user,
        (ONION, TODAY),
        (OLIVE_OIL, date(2026, 10, 15)),
        (OLIVE_OIL, date(2026, 10, 20)),  # later: not yet
    )
    async with make_sessionmaker(db_engine)() as session:
        reminder = await reminder_for(session, uid, TODAY)
        none = await reminder_for(session, uid, date(2026, 10, 30))

    assert reminder is not None
    assert reminder.body == "onions (today), oil (tomorrow). Open your pantry for ideas."
    assert none is None


@pytest.mark.usefixtures("foods")
async def test_reminders_go_once_a_day_at_the_users_hour(
    db_engine: AsyncEngine, new_user: NewUser
) -> None:
    await setup_user(db_engine, new_user, (ONION, TODAY))
    maker = make_sessionmaker(db_engine)
    push = FakePush()

    assert await send_due(maker, datetime(2026, 10, 14, 7, 0, tzinfo=UTC), SETTINGS, push) == 0
    assert await send_due(maker, NINE_IN_DUBLIN, SETTINGS, push) == 1
    assert await send_due(maker, NINE_IN_DUBLIN, SETTINGS, push) == 0  # already today
    assert [endpoint for endpoint, _ in push.sent] == ["https://push.example/1"]


@pytest.mark.usefixtures("foods")
async def test_unsubscribed_browsers_are_forgotten(
    db_engine: AsyncEngine, new_user: NewUser
) -> None:
    await setup_user(db_engine, new_user, (ONION, TODAY))
    maker = make_sessionmaker(db_engine)

    assert await send_due(maker, NINE_IN_DUBLIN, SETTINGS, FakePush(gone=True)) == 0

    async with maker() as session:
        assert (await session.scalars(select(PushSubscription))).all() == []


async def test_without_keys_nothing_is_sent(db_engine: AsyncEngine) -> None:
    assert await send_due(make_sessionmaker(db_engine), NINE_IN_DUBLIN, NO_KEYS) == 0


async def test_push_is_off_without_keys(api: httpx.AsyncClient, auth: Auth) -> None:
    app.dependency_overrides[get_settings] = lambda: NO_KEYS
    try:
        config = (await api.get("/me/push", headers=auth())).json()
        refused = await api.put(
            "/me/push",
            json={
                "endpoint": "https://push.example/2",
                "keys": {"p256dh": "p" * 20, "auth": "a" * 16},
            },
            headers=auth(),
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert config == {"enabled": False, "public_key": None, "subscribed": 0}
    assert refused.status_code == 409


@pytest.mark.usefixtures("push_enabled")
async def test_subscribe_and_unsubscribe(api: httpx.AsyncClient, auth: Auth) -> None:
    body = {"endpoint": "https://push.example/2", "keys": {"p256dh": "p" * 20, "auth": "a" * 16}}

    assert (await api.put("/me/push", json=body, headers=auth())).status_code == 204
    assert (await api.put("/me/push", json=body, headers=auth())).status_code == 204  # again
    config = (await api.get("/me/push", headers=auth())).json()
    assert config == {"enabled": True, "public_key": KEYS[0], "subscribed": 1}

    gone = await api.post(
        "/me/push/unsubscribe", json={"endpoint": body["endpoint"]}, headers=auth()
    )
    assert gone.status_code == 204
    assert (await api.get("/me/push", headers=auth())).json()["subscribed"] == 0
