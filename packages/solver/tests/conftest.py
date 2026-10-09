"""Hypothesis profiles: 'dev' locally, 'ci' (fewer, derandomised examples) when $CI is set;
override with $HYPOTHESIS_PROFILE. Scenario sweeps use `pytest.mark.parametrize("seed", ...)`
rather than @given, so every seed is reproducible and the suite stays fast."""

import os

from hypothesis import settings

settings.register_profile("dev", deadline=None)
settings.register_profile("ci", max_examples=50, derandomize=True, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci" if os.environ.get("CI") else "dev"))
