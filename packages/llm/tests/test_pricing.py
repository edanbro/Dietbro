"""List-price costs in micro-dollars, and what a realistic chat turn costs."""

import logging

import pytest

from larder_llm.client import HAIKU, SONNET, ModelCall, Usage
from larder_llm.pricing import PRICES, call_cost_micro_usd, cost_micro_usd, price_of


def test_sonnet_prices() -> None:
    # $2 / $10 per million tokens = 2 / 10 micro-dollars per token.
    assert cost_micro_usd(SONNET, Usage(input_tokens=1_000)) == 2_000
    assert cost_micro_usd(SONNET, Usage(output_tokens=1_000)) == 10_000
    assert cost_micro_usd(SONNET, Usage(cache_creation_input_tokens=1_000)) == 2_500  # 1.25x
    assert cost_micro_usd(SONNET, Usage(cache_read_input_tokens=1_000)) == 200


def test_haiku_prices() -> None:
    assert cost_micro_usd(HAIKU, Usage(input_tokens=1_000)) == 100
    assert cost_micro_usd(HAIKU, Usage(output_tokens=1_000)) == 500
    assert cost_micro_usd(HAIKU, Usage(cache_creation_input_tokens=1_000)) == 125
    assert cost_micro_usd(HAIKU, Usage(cache_read_input_tokens=1_000)) == 10


def test_costs_round_up_to_whole_micro_dollars() -> None:
    assert cost_micro_usd(HAIKU, Usage(input_tokens=1)) == 1  # 0.1 µ$
    assert cost_micro_usd(HAIKU, Usage()) == 0


def test_dated_and_suffixed_ids_use_their_family_price() -> None:
    assert price_of("claude-sonnet-5-5-20261001") == PRICES[SONNET]
    assert price_of("claude-sonnet-5") == PRICES["claude-sonnet-5"]


def test_unknown_models_are_charged_the_dearest_price(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        cost = cost_micro_usd("claude-mystery-9", Usage(output_tokens=1_000))
    assert cost == max(cost_micro_usd(m, Usage(output_tokens=1_000)) for m in PRICES)
    assert "claude-mystery-9" in caplog.text


def test_a_call_with_fallback_parts_is_priced_per_model() -> None:
    declined = Usage(input_tokens=1_000, output_tokens=100)
    served = Usage(input_tokens=1_000, output_tokens=300)
    call = ModelCall(
        "chat",
        "claude-opus-5-5",
        declined + served,
        900,
        "ok",
        parts=((SONNET, declined), ("claude-opus-5-5", served)),
    )
    assert call_cost_micro_usd(call) == (2_000 + 1_000) + (4_000 + 6_000)
    plain = ModelCall("chat", HAIKU, Usage(input_tokens=1_000), 10, "ok")
    assert call_cost_micro_usd(plain) == 100


def test_a_realistic_turn_costs_under_two_and_a_half_cents() -> None:
    """A fresh epoch: tools + system (~3.4k tokens) are read from the shared cache; each round
    writes the new tail (context block, tool results) to the cache and reads the rest; adaptive
    thinking at effort low keeps outputs short."""
    prefix = 3_400
    rounds = [
        # (cache read, cache write, uncached input, output)
        (prefix, 700, 3, 250),  # context + user message -> search_recipes
        (prefix + 700, 650, 3, 300),  # search results -> request_replan
        (prefix + 1_350, 500, 3, 280),  # replan outcome -> reply
    ]
    calls = [ModelCall("chat", SONNET, Usage(i, o, r, w), 2_000, "ok") for r, w, i, o in rounds]
    total = sum(call_cost_micro_usd(c) for c in calls)
    assert total < 25_000, total  # micro-dollars
    assert total > 10_000  # and the estimate isn't trivially low
