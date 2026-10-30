"""The app under test (used by conftest's `env` fixture): no models, a settable clock, settings
that ignore the environment and the greedy planner. Plans made with `make_plan(user, MON)` run
Monday 12 to Sunday 18 Oct 2026; it is Wednesday 14 Oct, 12:00 UTC."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

from larder_api import planning
from larder_api.changes.scope import Models
from larder_api.settings import Settings

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
MON = date(2026, 10, 12)
TUE, WED, THU, FRI, SAT, SUN = (MON + timedelta(days=d) for d in range(1, 7))
TEST_PLANNER: planning.Planner = partial(
    planning.run_planner, mode="greedy", time_limit_ms=2000, workers=1
)


def app_settings(**overrides: Any) -> Settings:
    """Defaults from the code, never from the environment (no key, no .env): validating
    skips the settings sources."""
    return Settings.model_validate({"planner": "greedy"} | overrides)


@dataclass
class AppEnv:
    auth: Callable[[str], dict[str, str]]  # Authorization header for a user
    now: datetime = NOW
    models: Models = field(default_factory=Models)
    settings: Settings = field(default_factory=app_settings)
    cache: planning.CatalogCache = field(default_factory=planning.CatalogCache)

    def clock(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)
