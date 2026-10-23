import pytest

from larder_core.cook_time import ahead_steps, cook_minutes, steps, timer_seconds


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("Simmer for 20 minutes.", [1200]),
        ("Cook for 20-25 mins, then rest for 5 minutes.", [1500, 300]),
        ("Bake 30 to 40 minutes", [2400]),
        ("Grill 8\u201310 mins", [600]),  # an en dash
        ("Roast for 1½ hours", [5400]),
        ("Leave for 1,5 hours", [5400]),
        ("Stir for a minute or two", [60]),
        ("Cook for a few minutes", [180]),
        ("Rest for two hours", [7200]),
        ("Chill for half an hour", [1800]),
        ("Use 1.5 kg of potatoes", []),
        ("Bake for 20 days", []),
    ],
)
def test_timer_seconds(text: str, seconds: list[int]) -> None:
    assert timer_seconds(text) == seconds


def test_steps_drop_numbering_and_blank_lines() -> None:
    method = "STEP 1\nChop the onion.\n\n2. Fry it for 5 minutes.\r\n3) Serve."
    assert steps(method) == ["Chop the onion.", "Fry it for 5 minutes.", "Serve."]


def test_named_times_add_up_step_by_step() -> None:
    method = "Fry the onion for 10 minutes.\nAdd the tomatoes and simmer for 20 minutes."
    assert cook_minutes(method) == 30


def test_a_sentence_counts_its_longest_time_once() -> None:
    # "stirring every 2 minutes" is inside the 25-minute simmer, not after it.
    assert cook_minutes("Simmer for 20-25 minutes, stirring every 2 minutes.") == 25


def test_cooking_without_a_time_takes_what_it_implies() -> None:
    assert cook_minutes("Bake until golden.") == 30
    assert cook_minutes("Cook the onion until soft.\nStir in the rice until absorbed.") == 20


def test_overnight_counts_unless_the_method_says_not_to() -> None:
    assert cook_minutes("Marinate the chicken overnight.") == 480
    assert cook_minutes("Do not marinate overnight, only for a few hours.") == 180


def test_headings_and_alternatives_take_no_time() -> None:
    method = (
        "Make the sauce:\nWhisk the sauce for 5 minutes.\n"
        "Soak the beans for 4 hours. Alternatively, soak them overnight."
    )
    assert cook_minutes(method) == 245


def test_hands_on_steps_take_at_least_a_minute_and_round_to_five() -> None:
    assert cook_minutes("Toast the bread.\nSpread the butter.") == 5
    assert cook_minutes("Slice the tomatoes.\nShred the lettuce.\nDress the salad.") == 5
    assert cook_minutes("Prove for 12 hours.\n" * 20) == 3 * 24 * 60  # capped
    assert cook_minutes("") is None
    assert cook_minutes("  \n ") is None


def test_a_stated_total_is_taken_at_its_word() -> None:
    method = "Prep:15min > Cook:30min > Ready in:45min\nSimmer for 20 minutes.\nBake 1 hour."
    assert cook_minutes(method) == 45
    assert cook_minutes("Total time: 1 hour 10 mins\nBake for 3 hours.") == 70
    # "Total cook time" is a sentence of the method (counted like one), not the recipe's total.
    assert cook_minutes("Fry for 5 minutes. Total cook time is about 6 to 8 minutes.") == 15


def test_a_tip_for_another_situation_is_only_read() -> None:
    method = (
        "Fried rice is best with day-old rice. If you don't have any, cook a batch. "
        "Let the rice dry out for 1 to 2 hours.\nFry the rice for 5 minutes."
    )
    assert cook_minutes(method) == 5  # the reading and the frying, not the drying


def test_bringing_to_the_boil_is_quicker_than_boiling() -> None:
    assert cook_minutes("Bring the stock to the boil.") == 5
    assert cook_minutes("Boil the potatoes.") == 10


def test_steps_that_need_a_head_start() -> None:
    method = (
        "Mix the spices into the yoghurt. Marinate the chicken overnight in the fridge.\n"
        "Soak the beans for 8 hours. Chill the dough for 30 minutes.\n"
        "Add the rest of the stock and simmer for 2 hours.\n"
        "Do not marinate overnight. If you don't have time, soak them for 2 hours.\n"
        "Alternatively, refrigerate overnight."
    )
    assert ahead_steps(method) == [
        "Marinate the chicken overnight in the fridge.",
        "Soak the beans for 8 hours.",
    ]
    assert ahead_steps("Fry the onion for 5 minutes.") == []
    # Overnight as an option needs only the time named.
    assert ahead_steps("Chill for at least 30 minutes, or overnight.") == []
    assert ahead_steps("Chill for at least 3 hours or overnight.") == [
        "Chill for at least 3 hours or overnight."
    ]
    assert cook_minutes("Chill for at least 30 minutes, or overnight.") == 30
