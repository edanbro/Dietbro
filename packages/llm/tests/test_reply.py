"""Templated offline replies: snapshots for representative outcomes."""

from datetime import date

import pytest

from larder_core.meals import Slot
from larder_llm.outcome import ChangeResult, DayKcal, Logged, ReplanOutcome, SlotChange
from larder_llm.reply import HELP_TEXT, OfflineReason, Reply, offline_reply
from larder_llm.rules import parse_rules

TODAY = date(2026, 10, 14)  # Wednesday
THU = date(2026, 10, 15)


def skip_outcome() -> ReplanOutcome:
    return ReplanOutcome(
        plan_id=7,
        version=3,
        results=[
            ChangeResult(
                index=0,
                intent="skip",
                date=TODAY,
                slot=Slot.DINNER,
                status="applied",
                message="Skipped tonight's dinner.",
            )
        ],
        changes=[
            SlotChange(
                date=TODAY,
                slot=Slot.DINNER,
                before="Lasagne",
                after=None,
                change_index=0,
                reason="skip",
            ),
            SlotChange(
                date=THU,
                slot=Slot.LUNCH,
                before="Lentil soup",
                after="Lentil soup",
                before_portions=2,
                after_portions=3,
                reason="resize",
            ),
        ],
        logged=[Logged(date=TODAY, slot=Slot.DINNER, kind="skipped", description="dinner", kcal=0)],
    )


def test_skip_offline_without_a_key() -> None:
    parsed = parse_rules("skip dinner tonight", TODAY)
    reply = offline_reply(parsed, [skip_outcome()], TODAY, reason="no_key", announce=True)
    assert reply == Reply(
        "(Simple mode: no AI model is set up, so I follow short, plain requests.)\n"
        "Skipped tonight's dinner.\n"
        "Logged: skipped Wed dinner.\n"
        "- Wed dinner: Lasagne -> no meal\n"
        "- Thu lunch: Lentil soup (1 -> 1.5 servings)"
    )


def test_off_plan_food_over_the_band_with_notes_and_warnings() -> None:
    outcome = ReplanOutcome(
        plan_id=8,
        version=4,
        fresh=True,
        results=[
            ChangeResult(
                index=0,
                intent="ate_off_plan",
                date=TODAY,
                slot=None,
                status="applied",
                message="Logged the pizza.",
            )
        ],
        changes=[
            SlotChange(
                date=TODAY,
                slot=Slot.DINNER,
                before="Chilli",
                after="Green salad",
                reason="rebalance",
            )
        ],
        logged=[
            Logged(
                date=TODAY,
                slot=Slot.LUNCH,
                kind="off_plan",
                description="2 slices of pizza",
                kcal=1150,
            ),
            Logged(
                date=TODAY,
                slot=Slot.SNACK,
                kind="skipped",
                description="snack",
                kcal=200,
                estimated=False,
            ),
        ],
        days=[
            DayKcal(
                date=TODAY, kcal=2450, min=1800, max=2100, floor=1500, relaxed=True, within=False
            ),
            DayKcal(
                date=THU, kcal=1900, min=1800, max=2100, floor=1500, relaxed=False, within=True
            ),
        ],
        warnings=["Friday is over your budget."],
        notes=["I took that as lunch."],
    )
    parsed = parse_rules("had 2 slices of pizza", TODAY)
    reply = offline_reply(parsed, [outcome], TODAY, reason="budget", announce=False)
    assert reply.text == (
        "I made a new plan for this week first.\n"
        "Logged the pizza.\n"
        "Logged: 2 slices of pizza, Wed lunch (~1,150 kcal, estimate); "
        "skipped Wed snack (~200 kcal counted for eating elsewhere).\n"
        "Wed is now ~2,450 kcal, above your 1,800-2,100 kcal range.\n"
        "I took that as lunch.\n"
        "Note: Friday is over your budget.\n"
        "- Wed dinner: Chilli -> Green salad"
    )
    assert reply.suggestions == ()


def test_a_failed_wish_and_an_unparsed_clause() -> None:
    outcome = ReplanOutcome(
        results=[
            ChangeResult(
                index=0,
                intent="craving",
                date=TODAY,
                slot=Slot.DINNER,
                status="failed",
                message="Nothing spicy fits tonight without breaking your allergies.",
            )
        ]
    )
    parsed = parse_rules("craving something spicy tonight, and can Friday be veggie?", TODAY)
    reply = offline_reply(parsed, [outcome], TODAY, reason="no_key", announce=False)
    assert reply.text == (
        "Nothing spicy fits tonight without breaking your allergies.\n"
        'I didn\'t catch "can Friday be veggie?".'
    )


def test_nothing_understood_gets_the_help_text() -> None:
    parsed = parse_rules("what's in the fridge?", TODAY)
    reply = offline_reply(parsed, [], TODAY, reason="model_error", announce=True)
    assert reply.text == (
        "(Simple mode: the AI assistant isn't responding right now.)\n"
        "I didn't catch \"what's in the fridge?\".\n" + HELP_TEXT
    )


def test_suggestions_are_passed_on() -> None:
    parsed = parse_rules("eating out on Friday", TODAY)
    reply = offline_reply(parsed, [ReplanOutcome()], TODAY, reason="no_key", announce=False)
    assert reply.suggestions == ("eating out Friday lunch", "eating out Friday dinner")


def test_understood_but_nothing_applied() -> None:
    parsed = parse_rules("skip dinner tonight", TODAY)
    reply = offline_reply(parsed, [], TODAY, reason="no_key", announce=False)
    assert reply.text == "I understood that, but couldn't update your plan just now."


def test_after_a_model_failure_only_the_outcomes_are_summarised() -> None:
    reply = offline_reply(None, [skip_outcome()], TODAY, reason="model_error", announce=False)
    assert reply.text.startswith("Skipped tonight's dinner.\n")
    assert HELP_TEXT not in reply.text
    assert reply.suggestions == ()
    assert offline_reply(None, [], TODAY, reason="model_error", announce=False).text == (
        "Nothing was changed."
    )


def test_long_change_lists_are_cut() -> None:
    changes = [
        SlotChange(
            date=date(2026, 10, 14 + i), slot=Slot.LUNCH, before="A", after="B", reason="rebalance"
        )
        for i in range(12)
    ]
    reply = offline_reply(
        None, [ReplanOutcome(changes=changes)], TODAY, reason="model_error", announce=False
    )
    lines = reply.text.splitlines()
    assert len(lines) == 8
    assert lines[-1] == "- ...and 5 more"
    assert lines[0] == "- Wed lunch: A -> B"
    assert "- Mon 26 Oct lunch: A -> B" not in lines


@pytest.mark.parametrize("reason", ["no_key", "budget", "model_error"])
def test_every_reason_has_an_announcement(reason: OfflineReason) -> None:
    parsed = parse_rules("skip dinner tonight", TODAY)
    first = offline_reply(parsed, [skip_outcome()], TODAY, reason=reason, announce=True)
    again = offline_reply(parsed, [skip_outcome()], TODAY, reason=reason, announce=False)
    assert first.text.startswith("(Simple mode: ")
    assert first.text.endswith(again.text)
    assert first.text.count("\n") == again.text.count("\n") + 1
