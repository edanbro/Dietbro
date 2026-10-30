"""Rate limits for routes that cost something to serve or are open to anyone.

Model calls, receipts and barcode lookups have their own limits (larder_api.changes.limits,
the receipt routes, larder_api.barcodes). These cover the rest: outbound page fetches (recipe
import), the solver (new plans and replans), quick-add, and the public share pages and calendar
feeds.

Each limit is a fixed window counted in Redis in one round trip: INCR, then EXPIRE NX so the
window's first hit sets its end. Over the limit the request gets 429 with Retry-After. If Redis
can't be reached the request goes ahead (logged): limits protect capacity, and a Redis outage
shouldn't take the app down with it. Tests run without the app's Redis, so limits are off there
unless a test overrides `get_counter`.

Client addresses: the socket peer, unless `trusted_proxy_hops` says how many of our own proxies
sit in front. Then it is the X-Forwarded-For entry that many from the right: the address our
outermost proxy saw, which a client can't forge (entries further left are whatever it sent).
"""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Protocol, cast

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from larder_api.auth import CurrentUser
from larder_api.settings import Settings, get_settings

__all__ = [
    "RULES",
    "Counter",
    "MemoryCounter",
    "RedisCounter",
    "Rule",
    "client_ip",
    "get_counter",
    "per_ip",
    "per_path",
    "per_user",
]

logger = logging.getLogger(__name__)

MINUTE, HOUR, DAY = 60, 3600, 86_400


@dataclass(frozen=True, slots=True)
class Rule:
    limit: int
    window_s: int


RULES: dict[str, Rule] = {
    "import_read": Rule(30, HOUR),  # fetches another site's page
    "import_save": Rule(60, HOUR),
    "share_create": Rule(100, DAY),
    "share_view": Rule(120, MINUTE),  # per link
    # Per address. The web app renders share pages on its server, so every viewer of a share
    # page arrives from the web server's address: this is a capacity guard, not per person.
    "share_view_ip": Rule(600, MINUTE),
    # Ticking a shared shopping list: straight from the shoppers' browsers.
    "share_tick": Rule(240, MINUTE),  # per link
    "share_tick_ip": Rule(240, MINUTE),
    "calendar_feed": Rule(60, HOUR),  # per feed; calendar apps refresh hourly at most
    "calendar_feed_ip": Rule(300, HOUR),
    "plan": Rule(120, HOUR),  # new plans and replans (solver time)
    "diary_log": Rule(300, DAY),
}


class Counter(Protocol):
    async def hit(self, key: str, window_s: int) -> int:
        """Count one request against `key`; the count in its window so far, this one included."""
        ...


@dataclass(frozen=True, slots=True)
class RedisCounter:
    redis: Redis

    async def hit(self, key: str, window_s: int) -> int:
        async with self.redis.pipeline(transaction=False) as pipe:
            pipe.incr(key)  # pyright: ignore[reportUnusedCoroutine]
            pipe.expire(key, window_s, nx=True)  # pyright: ignore[reportUnusedCoroutine]
            count, _ = await pipe.execute()
        return int(count)


@dataclass(slots=True)
class MemoryCounter:
    """For tests: the same counting in a dict (windows never expire)."""

    counts: dict[str, int] = field(default_factory=dict[str, int])

    async def hit(self, key: str, window_s: int) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


def get_counter(request: Request) -> Counter | None:
    """None when the app has no Redis (tests): limits are off."""
    resources = getattr(request.app.state, "resources", None)
    if resources is None:
        return None
    return RedisCounter(cast(Redis, resources.redis))


def client_ip(request: Request, settings: Settings) -> str:
    peer = request.client.host if request.client else "unknown"
    hops = settings.trusted_proxy_hops
    if hops <= 0:
        return peer
    forwarded = [
        a.strip() for h in request.headers.getlist("x-forwarded-for") for a in h.split(",")
    ]
    forwarded = [a for a in forwarded if a]
    return forwarded[-hops] if len(forwarded) >= hops else peer


Counted = Annotated[Counter | None, Depends(get_counter)]
Configured = Annotated[Settings, Depends(get_settings)]


async def _take(counter: Counter | None, settings: Settings, name: str, subject: str) -> None:
    if counter is None or not settings.rate_limits:
        return
    rule = RULES[name]
    limit = settings.rate_limit_overrides.get(name, rule.limit)
    now = time.time()
    window = int(now // rule.window_s)
    try:
        count = await counter.hit(f"rl:{name}:{subject}:{window}", rule.window_s)
    except Exception:
        logger.warning("rate limit %s not checked (Redis unavailable)", name, exc_info=True)
        return
    if count > limit:
        retry = max(1, int((window + 1) * rule.window_s - now))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ["Too many requests. Please try again a little later."],
            headers={"Retry-After": str(retry)},
        )


def _known(name: str) -> None:
    if name not in RULES:  # fail at import, not on the first request
        raise KeyError(f"no rate limit rule {name!r}")


def per_user(name: str) -> Callable[..., Awaitable[None]]:
    """A route dependency: at most RULES[name] requests per signed-in user."""
    _known(name)

    async def check(user: CurrentUser, counter: Counted, settings: Configured) -> None:
        await _take(counter, settings, name, f"u{user.id}")

    return check


def per_ip(name: str) -> Callable[..., Awaitable[None]]:
    """A route dependency: at most RULES[name] requests per client address."""
    _known(name)

    async def check(request: Request, counter: Counted, settings: Configured) -> None:
        await _take(counter, settings, name, client_ip(request, settings))

    return check


def per_path(name: str, param: str) -> Callable[..., Awaitable[None]]:
    """A route dependency: at most RULES[name] requests per value of path parameter `param`
    (a share link's or calendar feed's token)."""
    _known(name)

    async def check(request: Request, counter: Counted, settings: Configured) -> None:
        value = str(request.path_params.get(param, ""))[:64]
        await _take(counter, settings, name, value)

    return check
