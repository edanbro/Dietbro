"""Offline parser: plain-English chat messages -> typed changes, with no model.

Used when there is no API key, the user is over their LLM budget, or the model failed before any
change was applied (PLAN §7: "fall back to deterministic path"). It covers the four intents in
their common phrasings, splits a message into clauses (and / then / , / .), and reports the
clauses it didn't understand instead of guessing:

    "skip dinner tonight", "not having lunch tomorrow", "eating out on Friday"   -> Skip
    "had a pizza for lunch", "ate 2 slices of cake yesterday", "had a curry last night"
                                                                                 -> AteOffPlan
    "craving something spicy tonight", "I want lasagne on Thursday"              -> Craving
    "swap Thursday's dinner", "change tomorrow's lunch to something with rice"   -> Swap

Dates resolve against `today` (the user's local date): today / tonight / this morning /
tomorrow / yesterday / last night, weekday names and "on the 14th". A weekday means the most
recent such day (today included) for past tense and logged food (had, ate, grabbed, was), the
next such day (today included) otherwise. Meals: breakfast (brekkie), lunch, dinner (tea,
supper, tonight), snack; a missing meal is left as `slot=None` (the executor decides and says
what it assumed). eating_elsewhere is true only for eat-out phrases (eating out, out for dinner,
at a friend's / mum's, restaurant, takeaway), false otherwise (not hungry, fasting, skipping).
Questions ("should I skip dinner?") and negations ("I'm not skipping lunch", "don't change
Friday") produce no change. Craving strength is soft unless the user insists ("I really want",
"must have"). Every HELP_TEXT example parses.
"""

from dataclasses import dataclass
from datetime import date

from larder_llm.schemas import AteOffPlan, Craving, Skip, Swap

__all__ = ["RuleParse", "parse_rules"]

type RuleChange = Craving | AteOffPlan | Skip | Swap


@dataclass(frozen=True, slots=True)
class RuleParse:
    changes: tuple[RuleChange, ...]
    unparsed: tuple[str, ...]  # clauses that weren't understood (verbatim)
    # Complete phrases this parser would understand, offered as tap-to-send chips when a clause
    # was ambiguous ("skip Friday lunch", "skip Friday dinner"); each must parse.
    suggestions: tuple[str, ...] = ()

    @property
    def understood(self) -> bool:
        return bool(self.changes)


def parse_rules(text: str, today: date) -> RuleParse:
    raise NotImplementedError
