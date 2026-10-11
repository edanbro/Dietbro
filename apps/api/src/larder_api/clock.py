"""The current time as a dependency, so tests can pin it (dates near midnight, limits)."""

from collections.abc import Callable
from datetime import UTC, datetime

type Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def get_clock() -> Clock:
    return utc_now
