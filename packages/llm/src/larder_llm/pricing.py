"""What a model call costs, in micro-dollars (integers, rounded up), for `llm_calls` and the
per-user monthly cap. Prices are list prices per million tokens; a 5-minute cache write is billed
at 1.25x input and a cache read at the listed read price."""

import logging
import math
from dataclasses import dataclass
from decimal import Decimal

from larder_llm.client import Usage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Price:
    """US dollars per million tokens (= micro-dollars per token)."""

    input: Decimal
    output: Decimal
    cache_write: Decimal
    cache_read: Decimal


def _price(input_: str, output: str, cache_read: str) -> Price:
    i = Decimal(input_)
    return Price(i, Decimal(output), i * Decimal("1.25"), Decimal(cache_read))


# Haiku 5.5 is billed at a higher rate above 100K prompt tokens; our prompts stay far below.
PRICES: dict[str, Price] = {
    "claude-sonnet-5-5": _price("2", "10", "0.20"),
    "claude-sonnet-5": _price("2", "10", "0.20"),  # server-side refusal fallback target
    "claude-haiku-5-5": _price("0.10", "0.50", "0.01"),
    "claude-opus-5-5": _price("4", "20", "0.20"),
}
# Unknown model ids (a new fallback target, a typo in settings) are charged at the dearest
# known price, so the cap errs on the side of stopping early.
_DEAREST = max(PRICES.values(), key=lambda p: p.output)


def price_of(model: str) -> Price:
    for known, p in PRICES.items():
        if model == known or model.startswith(f"{known}-"):
            return p
    logger.warning("no price for model %r; charging the dearest known price", model)
    return _DEAREST


def cost_micro_usd(model: str, usage: Usage) -> int:
    p = price_of(model)
    total = (
        p.input * usage.input_tokens
        + p.output * usage.output_tokens
        + p.cache_write * usage.cache_creation_input_tokens
        + p.cache_read * usage.cache_read_input_tokens
    )
    return math.ceil(total)
