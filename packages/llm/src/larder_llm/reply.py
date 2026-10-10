"""Templated replies for the offline path and for turns the model couldn't finish: deterministic
text from what the executor did.

Short and specific, the same shape the model is asked to use: one or two sentences, then the
changed meals ("Thu dinner: Lasagne -> Chilli con carne"). Mentions estimates as estimates,
says what was assumed ("I took that as dinner"), says plainly what couldn't be done, lists the
clauses it didn't understand, and - once, when the mode changes - why replies are simple now.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from larder_llm.outcome import ReplanOutcome
from larder_llm.rules import RuleParse

__all__ = ["HELP_TEXT", "OfflineReason", "Reply", "offline_reply"]

HELP_TEXT = (
    'I can change your plan when you tell me things like "skip dinner tonight", '
    '"had pizza for lunch", "craving something spicy on Friday" or "swap Thursday\'s dinner".'
)

# Why this turn has no model: no API key configured, the user's daily/monthly budget is spent,
# or the model failed (after which only already-applied outcomes are summarised).
type OfflineReason = Literal["no_key", "budget", "model_error"]


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    suggestions: tuple[str, ...] = ()  # tap-to-send chips


def offline_reply(
    parsed: RuleParse | None,
    outcomes: list[ReplanOutcome],
    today: date,
    *,
    reason: OfflineReason,
    announce: bool,
) -> Reply:
    """`parsed` is None when the model already applied `outcomes` and failed afterwards (the
    reply then only summarises them). `announce`: add the one-line note on why replies are
    simple now (first offline turn after a model turn, or the first turn of a thread)."""
    raise NotImplementedError
