"""The biggest request body the API will read. FastAPI reads and parses a body before it checks
sign-in, so without this anyone could send a body as big as the server's memory. A declared length
over the limit is refused unread; a body that doesn't declare one is counted as it arrives.

Plain ASGI rather than `app.middleware("http")`, which wraps what it can't then stop part way.
"""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["BodyLimit"]

_TOO_BIG = "That request is too big."


class BodyLimit:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            response = JSONResponse({"detail": [_TOO_BIG]}, status_code=413)
            await response(scope, receive, send)
            return
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    # An HTTPException comes out as a response, wherever the body was being read.
                    raise HTTPException(413, _TOO_BIG)  # pyright: ignore[reportArgumentType]
            return message

        await self.app(scope, counted, send)
