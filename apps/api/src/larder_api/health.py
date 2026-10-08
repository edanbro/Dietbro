import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from larder_api.resources import Resources, get_resources

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

type Check = Callable[[], Awaitable[object]]

CHECK_TIMEOUT_S = 2.0


class Health(BaseModel):
    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, Literal["ok", "error"]]


def get_checks(resources: Annotated[Resources, Depends(get_resources)]) -> dict[str, Check]:
    async def database() -> None:
        async with resources.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def redis() -> None:
        await resources.redis.ping()  # pyright: ignore[reportUnknownMemberType]

    return {"database": database, "redis": redis}


@router.get("/healthz", operation_id="getHealth")
async def healthz() -> Health:
    """Liveness: the process is up and serving requests."""
    return Health()


@router.get(
    "/readyz",
    operation_id="getReadiness",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": Readiness}},
)
async def readyz(
    response: Response,
    checks: Annotated[dict[str, Check], Depends(get_checks)],
) -> Readiness:
    """Readiness: every backing service (Postgres, Redis) answers."""

    async def run(name: str, check: Check) -> tuple[str, Literal["ok", "error"]]:
        try:
            await asyncio.wait_for(check(), CHECK_TIMEOUT_S)
        except Exception:
            logger.warning("readiness check %s failed", name, exc_info=True)
            return name, "error"
        return name, "ok"

    results = dict(await asyncio.gather(*(run(name, check) for name, check in checks.items())))
    ready = all(result == "ok" for result in results.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readiness(status="ok" if ready else "degraded", checks=results)
