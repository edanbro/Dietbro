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

from larder_llm.outcome import Logged, ReplanOutcome, SlotChange
from larder_llm.rules import RuleParse

__all__ = ["HELP_TEXT", "OfflineReason", "RecipeAnswer", "Reply", "offline_reply"]

HELP_TEXT = (
    'I can change your plan when you tell me things like "skip dinner tonight", '
    '"had pizza for lunch", "craving something spicy on Friday" or "swap Thursday\'s dinner".'
)

# Why this turn has no model: no API key configured, the user's daily/monthly budget is spent,
# or the model failed (after which only already-applied outcomes are summarised).
type OfflineReason = Literal["no_key", "budget", "model_error"]


@dataclass(frozen=True, slots=True)
class RecipeAnswer:
    """Recipes found for a question like "what can I make with spinach?" (rules.recipe_question):
    `query` the foods named ("" for what the pantry can make), `names` the safe recipes found."""

    query: str
    names: tuple[str, ...]


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
    recipes: RecipeAnswer | None = None,
) -> Reply:
    """`parsed` is None when the model already applied `outcomes` and failed afterwards (the
    reply then only summarises them). `announce`: add the one-line note on why replies are
    simple now (first offline turn after a model turn, or the first turn of a thread)."""
    lines = [_ANNOUNCE[reason]] if announce else []
    summary = [line for outcome in outcomes for line in _summary(outcome, today)]
    lines += summary
    if parsed is None:
        if not summary:
            lines.append("Nothing was changed.")
        return Reply("\n".join(lines))
    if recipes is not None and not parsed.understood:
        lines += _recipe_lines(recipes)
        chips = tuple(f"swap tonight's dinner for {n.lower()}" for n in recipes.names[:2])
        return Reply("\n".join(lines), chips)
    if parsed.understood and not summary:
        lines.append("I understood that, but couldn't update your plan just now.")
    if parsed.unparsed:
        quoted = ", ".join(f'"{clause}"' for clause in parsed.unparsed)
        lines.append(f"I didn't catch {quoted}.")
    if not parsed.understood:
        lines.append(HELP_TEXT)
    return Reply("\n".join(lines), parsed.suggestions)


def _recipe_lines(answer: RecipeAnswer) -> list[str]:
    where = f"with {answer.query}" if answer.query else "from your pantry"
    if not answer.names:
        if answer.query:
            return [f"I couldn't find a recipe {where} that's safe for you."]
        return ["Nothing safe uses what's in your pantry yet. Add what you have and ask again."]
    return [
        f"Recipes {where}: {', '.join(answer.names)}.",
        f'To have one, say "swap tonight\'s dinner for {answer.names[0].lower()}" (or any day '
        "and meal).",
    ]


_ANNOUNCE: dict[OfflineReason, str] = {
    "no_key": "(Simple mode: no AI model is set up, so I follow short, plain requests.)",
    "budget": "(Simple mode: you've used your AI chat allowance for now, so I follow short, "
    "plain requests until it resets.)",
    "model_error": "(Simple mode: the AI assistant isn't responding right now.)",
}
_MAX_CHANGE_LINES = 8


def _summary(outcome: ReplanOutcome, today: date) -> list[str]:
    """Sentences first (what happened, what was logged, days off target, notes), then the
    changed meals as a short list."""
    lines: list[str] = []
    if outcome.fresh:
        lines.append("I made a new plan for this week first.")
    lines += [r.message for r in outcome.results if r.message]
    if outcome.logged:
        lines.append(
            "Logged: " + "; ".join(_logged(entry, today) for entry in outcome.logged) + "."
        )
    for day in outcome.days:
        if not day.within:
            side = "above" if day.kcal > day.max else "below"
            lines.append(
                f"{_day(day.date, today)} is now ~{day.kcal:,} kcal, {side} your "
                f"{day.min:,}-{day.max:,} kcal range."
            )
    lines += outcome.notes
    lines += [f"Note: {warning}" for warning in outcome.warnings]
    changes = [_change(c, today) for c in outcome.changes]
    if len(changes) > _MAX_CHANGE_LINES:
        more = len(changes) - _MAX_CHANGE_LINES + 1
        changes = [*changes[: _MAX_CHANGE_LINES - 1], f"...and {more} more"]
    lines += [f"- {c}" for c in changes]
    return lines


def _day(d: date, today: date) -> str:
    return f"{d:%a}" if abs((d - today).days) <= 6 else f"{d:%a} {d.day} {d:%b}"


def _meal(d: date, slot: str | None, today: date) -> str:
    return f"{_day(d, today)} {slot}" if slot else _day(d, today)


def _logged(entry: Logged, today: date) -> str:
    when = _meal(entry.date, entry.slot, today)
    if entry.kind == "skipped":
        if entry.kcal:
            return f"skipped {when} (~{entry.kcal:,} kcal counted for eating elsewhere)"
        return f"skipped {when}"
    estimate = ", estimate" if entry.estimated else ""
    return f"{entry.description}, {when} (~{entry.kcal:,} kcal{estimate})"


def _change(c: SlotChange, today: date) -> str:
    when = _meal(c.date, c.slot, today)
    if (
        c.before == c.after
        and c.before_portions is not None
        and c.after_portions is not None
        and c.before_portions != c.after_portions
    ):
        b, a = c.before_portions / 2, c.after_portions / 2
        return f"{when}: {c.after} ({b:g} -> {a:g} servings)"
    return f"{when}: {c.before or 'no meal'} -> {c.after or 'no meal'}"
