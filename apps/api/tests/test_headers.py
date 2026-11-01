"""Headers on every API response, what cross-origin pages may read, the biggest request body the
API reads, and what its access log keeps."""

import logging
from typing import Any

import httpx
import pytest

from larder_api.logs import HideTokens
from larder_api.main import app

ORIGIN = "http://localhost:3000"


async def test_every_response_has_the_security_headers(api: httpx.AsyncClient) -> None:
    for path in ("/healthz", "/public/share/nobody-has-this-token"):
        response = await api.get(path)
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"


async def test_the_web_app_may_read_retry_after(api: httpx.AsyncClient) -> None:
    response = await api.get("/healthz", headers={"Origin": ORIGIN})
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "retry-after" in response.headers["access-control-expose-headers"].lower()


async def test_a_body_declared_too_big_is_refused_unread_and_before_sign_in(
    api: httpx.AsyncClient,
) -> None:
    response = await api.post("/plans", content=b"x" * 10_000_000)
    assert response.status_code == 413
    assert response.json()["detail"] == ["That request is too big."]
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_a_body_that_declares_no_length_stops_being_read_at_the_limit() -> None:
    chunks = 0

    async def receive() -> dict[str, Any]:
        nonlocal chunks
        chunks += 1
        return {"type": "http.request", "body": b"x" * 1_000_000, "more_body": chunks < 50}

    sent: list[dict[str, Any]] = []

    async def send(message: Any) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/plans",
        "raw_path": b"/plans",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("1.2.3.4", 1),
        "server": ("test", 80),
        "scheme": "http",
        "root_path": "",
    }
    await app(scope, receive, send)  # pyright: ignore[reportArgumentType]

    assert chunks <= 10  # the 9 MB limit, not the 50 MB sent
    assert next(m["status"] for m in sent if m["type"] == "http.response.start") == 413


@pytest.mark.parametrize(
    ("path", "shown"),
    [
        ("/public/share/abc123?x=1", "/public/share/***?x=1"),
        ("/public/share/abc123/items/7", "/public/share/***/items/7"),
        ("/share/abc123", "/share/***"),
        ("/calendar/abc123.ics", "/calendar/***"),
        ("/me/calendar", "/me/calendar"),
        ("/plans", "/plans"),
    ],
)
def test_the_access_log_keeps_tokens_out(path: str, shown: str) -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s %s %s %d",
        ("1.2.3.4:5", "GET", path, "1.1", 200),
        None,
    )
    assert HideTokens().filter(record)
    assert record.getMessage() == f"1.2.3.4:5 GET {shown} 1.1 200"
