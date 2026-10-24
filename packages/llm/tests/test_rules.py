"""The offline rule parser against a fixed Wednesday: a table of phrasings and their changes."""

import re
from datetime import date

import pytest

from larder_core.meals import Slot
from larder_llm.reply import HELP_TEXT
from larder_llm.rules import RuleChange, RuleParse, parse_rules, recipe_question
from larder_llm.schemas import AteOffPlan, Craving, OffPlanItem, Skip, Swap, When

TODAY = date(2026, 10, 14)  # a Wednesday
MON_PAST, TUE, WED, THU, FRI, SAT, SUN = (date(2026, 10, d) for d in range(12, 19))
MON_NEXT, TUE_20, WED_21 = date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)
B, L, D = Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER


def skip(day: date, slot: Slot | None = None, *, out: bool = False) -> Skip:
    return Skip(intent="skip", when=When(date=day, slot=slot), eating_elsewhere=out)


def ate(
    day: date, slot: Slot | None, description: str, *items: tuple[str, str | None]
) -> AteOffPlan:
    return AteOffPlan(
        intent="ate_off_plan",
        when=When(date=day, slot=slot),
        description=description,
        items=[OffPlanItem(name=n, quantity=q) for n, q in items],
    )


def crave(
    day: date,
    slot: Slot | None = None,
    *,
    dish: str | None = None,
    tags: tuple[str, ...] = (),
    hard: bool = False,
) -> Craving:
    return Craving(
        intent="craving",
        when=When(date=day, slot=slot),
        dish=dish,
        tags=list(tags),
        strength="hard" if hard else "soft",
    )


def swap(
    day: date, slot: Slot | None = None, *, dish: str | None = None, tags: tuple[str, ...] = ()
) -> Swap:
    return Swap(intent="swap", when=When(date=day, slot=slot), dish=dish, tags=list(tags))


TABLE: list[tuple[str, list[RuleChange]]] = [
    # --- skip ---------------------------------------------------------------------------------
    ("skip dinner tonight", [skip(WED, D)]),
    ("not having lunch tomorrow", [skip(THU, L)]),
    ("eating out on Friday", [skip(FRI, out=True)]),
    ("I'm skipping breakfast", [skip(WED, B)]),
    ("not hungry tonight", [skip(WED, D)]),
    ("I won't need lunch on Thursday", [skip(THU, L)]),
    ("at my mum's for dinner on Saturday", [skip(SAT, D, out=True)]),
    ("going to a restaurant tonight", [skip(WED, D, out=True)]),
    ("getting a takeaway on Friday night", [skip(FRI, D, out=True)]),
    ("out for dinner tomorrow", [skip(THU, D, out=True)]),
    ("skipping tea", [skip(WED, D)]),
    ("no supper for me on Sunday", [skip(SUN, D)]),
    ("I'll skip brekkie tomorrow", [skip(THU, B)]),
    ("skip lunch and dinner tomorrow", [skip(THU, L), skip(THU, D)]),
    ("I didn't eat lunch", [skip(WED, L)]),
    ("skipped breakfast on Monday", [skip(MON_PAST, B)]),
    ("fasting tomorrow", [skip(THU)]),
    ("dinner at Sarah's on Friday", [skip(FRI, D, out=True)]),
    ("skip dinner tonight, eating at my mum's", [skip(WED, D, out=True)]),
    ("I won't be home for dinner on the 20th", [skip(TUE_20, D)]),
    ("ate out last night", [skip(TUE, D, out=True)]),
    ("Skip Dinner Tonight!", [skip(WED, D)]),
    ("tomorrow, skip lunch", [skip(THU, L)]),
    ("skip dinner tonight and lunch tomorrow", [skip(WED, D), skip(THU, L)]),
    # --- ate off plan -------------------------------------------------------------------------
    ("had pizza for lunch", [ate(WED, L, "pizza", ("pizza", None))]),
    ("ate 2 slices of cake yesterday", [ate(TUE, None, "2 slices of cake", ("cake", "2 slices"))]),
    ("had a curry last night", [ate(TUE, D, "curry", ("curry", None))]),
    (
        "I had a Big Mac and fries for lunch",
        [ate(WED, L, "Big Mac and fries", ("Big Mac", None), ("fries", None))],
    ),
    ("grabbed a meal deal at lunch", [ate(WED, L, "meal deal", ("meal deal", None))]),
    ("had a takeaway on Monday", [ate(MON_PAST, None, "takeaway", ("takeaway", None))]),
    ("this morning I had a croissant", [ate(WED, B, "croissant", ("croissant", None))]),
    ("had cake for tea on Wednesday", [ate(WED, D, "cake", ("cake", None))]),
    (
        "had 300g of rice and a coke earlier",
        [ate(WED, None, "300g of rice and a coke", ("rice", "300 g"), ("coke", None))],
    ),
    ("had a large pizza on the 12th", [ate(MON_PAST, None, "large pizza", ("pizza", "1 large"))]),
    (
        "I'm having fish and chips tonight",
        [ate(WED, D, "fish and chips", ("fish", None), ("chips", None))],
    ),
    ("had a slice of toast this morning", [ate(WED, B, "slice of toast", ("toast", "1 slice"))]),
    # --- cravings -----------------------------------------------------------------------------
    ("craving something spicy tonight", [crave(WED, D, tags=("spicy",))]),
    ("I want lasagne on Thursday", [crave(THU, dish="lasagne")]),
    ("craving something spicy on Friday", [crave(FRI, tags=("spicy",))]),
    ("I really want a curry tonight", [crave(WED, D, dish="curry", hard=True)]),
    ("must have pizza on Saturday", [crave(SAT, dish="pizza", hard=True)]),
    ("fancy a burger tomorrow", [crave(THU, dish="burger")]),
    ("in the mood for something light for lunch", [crave(WED, L, tags=("light",))]),
    ("I'd love ramen for dinner on the 21st", [crave(WED_21, D, dish="ramen")]),
    ("can I have pasta tonight?", [crave(WED, D, dish="pasta")]),
    ("could go for something hearty next Monday", [crave(MON_NEXT, tags=("hearty",))]),
    ("craving spicy food tomorrow night", [crave(THU, D, tags=("spicy",))]),
    (
        "I need something quick and light tonight",
        [crave(WED, D, tags=("quick", "light"), hard=True)],
    ),
    # --- swaps --------------------------------------------------------------------------------
    ("swap Thursday's dinner", [swap(THU, D)]),
    ("change tomorrow's lunch to something with rice", [swap(THU, L, tags=("rice",))]),
    ("swap dinner tonight for a curry", [swap(WED, D, dish="curry")]),
    ("replace Friday's lunch with pasta", [swap(FRI, L, dish="pasta")]),
    ("something different for dinner on Friday", [swap(FRI, D)]),
    ("can you swap tonight's dinner?", [swap(WED, D)]),
    ("switch lunch on Monday", [swap(MON_NEXT, L)]),
    ("swap Friday", [swap(FRI)]),
    # --- several clauses ----------------------------------------------------------------------
    (
        "had pizza for lunch and skip dinner tonight",
        [ate(WED, L, "pizza", ("pizza", None)), skip(WED, D)],
    ),
    ("skip lunch tomorrow and I want a curry tonight", [skip(THU, L), crave(WED, D, dish="curry")]),
    (
        "Had a burger and chips for lunch. Then skip dinner",
        [ate(WED, L, "burger and chips", ("burger", None), ("chips", None)), skip(WED, D)],
    ),
    # --- found by testing ----------------------------------------------------------------------
    ("something vegetarian on Friday", [crave(FRI, tags=("vegetarian",))]),
    ("anything with rice tomorrow", [crave(THU, tags=("rice",))]),
    ("I don't like tonight's dinner", [swap(WED, D)]),
    ("I hate Friday's lunch", [swap(FRI, L)]),
    ("make friday dinner pasta", [crave(FRI, D, dish="pasta", hard=True)]),
    ("skip all my meals on Saturday", [skip(SAT, B), skip(SAT, L), skip(SAT, D)]),
    (
        "eating out all day Sunday",
        [skip(SUN, B, out=True), skip(SUN, L, out=True), skip(SUN, D, out=True)],
    ),
    ("not hungry, skip lunch", [skip(WED, L)]),
    # --- no change: questions and negations ---------------------------------------------------
    ("should I skip dinner?", []),
    ("I'm not skipping lunch", []),
    ("don't change Friday", []),
    ("I didn't have pizza", []),
    ("what's for dinner tonight?", []),
    ("why is there so much rice", []),
    ("not in the mood for curry", []),
    ("the weather is nice", []),
]


@pytest.mark.parametrize(("text", "expected"), TABLE, ids=[t for t, _ in TABLE])
def test_phrasings(text: str, expected: list[RuleChange]) -> None:
    parsed = parse_rules(text, TODAY)
    assert list(parsed.changes) == expected
    assert parsed.understood == bool(expected)
    if not expected:
        assert parsed.unparsed == (text,)


def test_the_table_is_big_enough() -> None:
    assert len(TABLE) >= 45
    intents = {c.intent for _, changes in TABLE for c in changes}
    assert intents == {"skip", "ate_off_plan", "craving", "swap"}


def test_unparsed_clauses_are_reported_verbatim() -> None:
    parsed = parse_rules("Had pizza for lunch, and can Friday be veggie?", TODAY)
    assert parsed.changes == (ate(WED, L, "pizza", ("pizza", None)),)
    assert parsed.unparsed == ("can Friday be veggie?",)

    parsed = parse_rules("skip dinner tonight. the weather is lovely", TODAY)
    assert parsed.changes == (skip(WED, D),)
    assert parsed.unparsed == ("the weather is lovely",)


def test_greetings_and_thanks_are_ignored() -> None:
    parsed = parse_rules("Hi! Skip dinner tonight please. Thanks", TODAY)
    assert parsed.changes == (skip(WED, D),)
    assert parsed.unparsed == ()
    assert parse_rules("hello there", TODAY) == RuleParse((), ())


def test_follow_up_clauses_explain_a_skip() -> None:
    assert parse_rules("no dinner tonight, not hungry", TODAY).changes == (skip(WED, D),)
    assert parse_rules("had a big lunch so skip dinner", TODAY).changes == (skip(WED, D),)


def test_empty_text() -> None:
    parsed = parse_rules("   ", TODAY)
    assert parsed == RuleParse((), (), ())


@pytest.mark.parametrize(
    ("text", "suggestions"),
    [
        ("eating out on Friday", ("eating out Friday lunch", "eating out Friday dinner")),
        ("swap Friday", ("swap Friday lunch", "swap Friday dinner")),
        ("fasting tomorrow", ("skip lunch tomorrow", "skip dinner tomorrow")),
        ("not hungry", ("skip lunch today", "skip dinner today")),
        ("skipped a meal yesterday", ("skipped lunch yesterday", "skipped dinner yesterday")),
        ("swap a meal on the 23rd", ("swap lunch on the 23rd", "swap dinner on the 23rd")),
    ],
)
def test_missing_meal_suggestions_parse(text: str, suggestions: tuple[str, ...]) -> None:
    parsed = parse_rules(text, TODAY)
    assert parsed.suggestions == suggestions
    (change,) = parsed.changes
    assert change.when.slot is None
    for suggestion, slot in zip(suggestions, (L, D), strict=True):
        (picked,) = parse_rules(suggestion, TODAY).changes
        assert picked.when == When(date=change.when.date, slot=slot)
        assert picked.intent == change.intent
        if isinstance(change, Skip):
            assert isinstance(picked, Skip)
            assert picked.eating_elsewhere == change.eating_elsewhere


def test_every_suggestion_in_the_table_parses() -> None:
    for text, _ in TABLE:
        for suggestion in parse_rules(text, TODAY).suggestions:
            assert parse_rules(suggestion, TODAY).understood, (text, suggestion)


@pytest.mark.parametrize(
    ("text", "hard"),
    [
        ("I want a curry tonight", False),
        ("I really want a curry tonight", True),
        ("must have a curry tonight", True),
        ("I need a curry tonight", True),
        ("dying for a curry tonight", True),
        ("fancy a curry tonight", False),
    ],
)
def test_craving_strength(text: str, hard: bool) -> None:
    (change,) = parse_rules(text, TODAY).changes
    assert isinstance(change, Craving)
    assert change.strength == ("hard" if hard else "soft")


@pytest.mark.parametrize(
    ("text", "day"),
    [
        ("had a curry on Monday", MON_PAST),
        ("craving a curry on Monday", MON_NEXT),
        ("had a curry on Wednesday", WED),
        ("craving a curry on Wednesday", WED),
        ("craving a curry next Wednesday", WED_21),
        ("had a curry last Wednesday", date(2026, 10, 7)),
        ("had a curry on the 2nd", date(2026, 10, 2)),
        ("craving a curry on the 2nd", date(2026, 11, 2)),
        ("craving a curry on the 14th", WED),
    ],
)
def test_weekdays_and_dates_follow_the_tense(text: str, day: date) -> None:
    (change,) = parse_rules(text, TODAY).changes
    assert change.when.date == day


def test_help_text_examples_parse() -> None:
    examples = re.findall(r'"([^"]+)"', HELP_TEXT)
    assert len(examples) == 4
    for example in examples:
        assert parse_rules(example, TODAY).understood, example


def test_limits_hold_for_long_input() -> None:
    food = " and ".join(f"item{i}" for i in range(15))
    (change,) = parse_rules(f"had {food} for lunch", TODAY).changes
    assert isinstance(change, AteOffPlan)
    assert len(change.items) == 10
    assert len(change.description) <= 200
    many = ". ".join(["skip dinner tonight"] * 10)
    assert len(parse_rules(many, TODAY).changes) <= 6


@pytest.mark.parametrize(
    ("text", "query"),
    [
        ("What can I make with spinach, milk before they go off?", "spinach, milk"),
        ("any recipes using leftover chicken", "chicken"),
        ("which recipes use tofu", "tofu"),
        ("what can I make with chicken for dinner tomorrow?", "chicken"),
        ("what can I cook?", ""),
        ("What should we make tonight?", ""),
        ("what can I make from my pantry", ""),
        ("got any ideas?", ""),
        ("skip dinner tonight", None),
        ("what's for dinner?", None),
        ("I want chicken tomorrow", None),
    ],
)
def test_recipe_questions(text: str, query: str | None) -> None:
    assert recipe_question(text) == query
