"""Headers on every API response, and what cross-origin pages may read."""

import httpx

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
