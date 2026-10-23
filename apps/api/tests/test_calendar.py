"""The private calendar feed (/me/calendar, /calendar/{token}.ics). This week's plan starts
Monday 12 Oct 2026; it is Wednesday 14 Oct, 12:00 UTC (chat_support)."""

from collections.abc import Awaitable, Callable, Coroutine
from datetime import date
from typing import Any

import httpx
from chat_support import ChatEnv

NewUser = Callable[..., Awaitable[int]]
MakePlan = Callable[[int, date], Coroutine[Any, Any, int]]
MON = date(2026, 10, 12)


async def test_feed_lists_the_planned_meals(
    api: httpx.AsyncClient,
    chat: ChatEnv,
    menu: dict[str, int],
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    user_id = await new_user("user_a")
    await make_plan(user_id, MON)
    auth = chat.auth("user_a")

    off = (await api.get("/me/calendar", headers=auth)).json()
    assert off == {
        "enabled": False,
        "path": None,
        "times": {"breakfast": "08:00", "lunch": "13:00", "dinner": "19:00", "snack": "16:00"},
    }
    on = (await api.post("/me/calendar", headers=auth)).json()
    assert on["enabled"] is True
    path = on["path"]
    assert path.startswith("/calendar/")
    assert path.endswith(".ics")

    feed = await api.get(path)  # no sign-in
    assert feed.status_code == 200
    assert feed.headers["content-type"].startswith("text/calendar")
    text = feed.text
    assert text.startswith("BEGIN:VCALENDAR\r\n")
    assert text.count("BEGIN:VEVENT") == 7 * 3  # this week's breakfasts, lunches and dinners
    assert "UID:2026-10-14-dinner@localhost" in text
    assert "DTSTART:20261014T190000" in text
    assert "/recipes/" in text
    assert "/cook?servings=" in text


async def test_times_can_change_and_reset_retires_the_old_address(
    api: httpx.AsyncClient,
    chat: ChatEnv,
    menu: dict[str, int],
    new_user: NewUser,
    make_plan: MakePlan,
) -> None:
    await make_plan(await new_user("user_a"), MON)
    auth = chat.auth("user_a")
    first = (await api.post("/me/calendar", headers=auth)).json()["path"]

    times = {"breakfast": "07:15", "lunch": "12:30", "dinner": "18:45", "snack": "15:00"}
    saved = await api.put("/me/calendar/times", json=times, headers=auth)
    assert saved.json()["times"] == times
    assert "DTSTART:20261014T184500" in (await api.get(first)).text

    bad = await api.put("/me/calendar/times", json={**times, "dinner": "25:00"}, headers=auth)
    assert bad.status_code == 422

    second = (await api.post("/me/calendar", headers=auth)).json()["path"]
    assert second != first
    assert (await api.get(first)).status_code == 404
    assert (await api.get(second)).status_code == 200

    await api.delete("/me/calendar", headers=auth)
    assert (await api.get(second)).status_code == 404


async def test_unknown_feeds(api: httpx.AsyncClient) -> None:
    assert (await api.get("/calendar/not-a-real-token-123.ics")).status_code == 404
    assert (await api.get("/calendar/x.ics")).status_code == 404


async def test_settings_need_sign_in(api: httpx.AsyncClient) -> None:
    assert (await api.get("/me/calendar")).status_code == 401
