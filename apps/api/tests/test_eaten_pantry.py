"""The pantry arithmetic of marking a meal eaten (larder_api.eaten): what a meal needs, what is
taken from which pantry item, and what undo gives back. Pure: no database."""

from datetime import date

import pytest

from larder_api.eaten import Line, Stock, Taken, give_back, meal_needs, take

OATS, APPLE, SALT, MILK = 1, 2, 3, 4
MON = date(2026, 10, 12)


def stock(
    item_id: int,
    food_id: int,
    grams: float,
    quantity: float | None = None,
    unit: str = "g",
    expires_on: date | None = None,
    *,
    convertible: bool = True,
) -> Stock:
    return Stock(
        item_id=item_id,
        food_id=food_id,
        grams=grams,
        quantity=grams if quantity is None else quantity,
        unit=unit,
        expires_on=expires_on,
        convertible=convertible,
    )


# --- what a meal needs ------------------------------------------------------------------------


def test_needs_are_the_planners_grams_per_portion_times_portions() -> None:
    """A recipe for 2 servings with 200 g oats is 50 g a portion (half a serving): 3 portions
    take 150 g. Lines of one food add up; unresolved lines and staples take nothing."""
    lines = [
        Line(OATS, 200, staple=False),
        Line(APPLE, 301, staple=False),  # 75.25 g a portion -> 76 g, as the planner counts it
        Line(OATS, 20, staple=False),
        Line(SALT, 5, staple=True),
        Line(None, 100, staple=False),
        Line(MILK, None, staple=False),
    ]
    assert meal_needs(lines, servings=2, portions=3) == {OATS: 150 + 15, APPLE: 3 * 76}


def test_needs_with_no_servings_are_empty() -> None:
    assert meal_needs([Line(OATS, 200, staple=False)], servings=0, portions=2) == {}


# --- taking from the pantry -------------------------------------------------------------------


def test_takes_soonest_expiring_first_and_never_below_zero() -> None:
    later = stock(1, OATS, 500, expires_on=date(2026, 12, 1))
    sooner = stock(2, OATS, 100, expires_on=date(2026, 10, 20))
    keeps = stock(3, OATS, 1000)  # no date: last
    taken = take({OATS: 450}, [later, keeps, sooner])
    assert taken == [
        Taken(2, OATS, 100, 100, "g"),
        Taken(1, OATS, 350, 350, "g"),
    ]


def test_takes_what_there_is_when_the_pantry_is_short() -> None:
    taken = take({OATS: 450}, [stock(1, OATS, 120)])
    assert taken == [Taken(1, OATS, 120, 120, "g")]


def test_amounts_are_in_the_items_own_unit() -> None:
    """3 large apples weigh 600 g: taking 250 g is 1.25 of them; taking everything is exactly
    the quantity on hand."""
    apples = stock(1, APPLE, 600, quantity=3, unit="large")
    assert take({APPLE: 250}, [apples]) == [Taken(1, APPLE, 250, 1.25, "large")]
    assert take({APPLE: 900}, [apples]) == [Taken(1, APPLE, 600, 3, "large")]


def test_items_that_dont_convert_or_are_empty_are_skipped() -> None:
    vague = stock(1, OATS, 300, quantity=1, unit="handful", convertible=False)
    empty = stock(2, OATS, 0, quantity=0)
    other_food = stock(3, APPLE, 300)
    exact = stock(4, OATS, 40, expires_on=date(2027, 1, 1))
    assert take({OATS: 100}, [vague, empty, other_food, exact]) == [Taken(4, OATS, 40, 40, "g")]


def test_ties_on_expiry_go_by_item_id() -> None:
    a = stock(7, OATS, 50, expires_on=MON)
    b = stock(3, OATS, 50, expires_on=MON)
    assert [t.item_id for t in take({OATS: 60}, [a, b])] == [3, 7]


def test_nothing_needed_takes_nothing() -> None:
    assert take({}, [stock(1, OATS, 100)]) == []
    assert take({OATS: 0}, [stock(1, OATS, 100)]) == []


@pytest.mark.parametrize("need", [1, 99.5, 100, 150, 1000])
def test_taking_then_giving_back_restores_the_item_exactly(need: float) -> None:
    item = stock(1, OATS, 100, quantity=2.5, unit="cup")
    [taken] = take({OATS: need}, [item])
    left_g, left_q = item.grams - taken.grams, item.quantity - taken.quantity
    assert left_g >= 0
    assert left_q >= 0
    assert give_back(left_g, left_q, "cup", taken) == pytest.approx((100, 2.5))


def test_taken_round_trips_through_json() -> None:
    taken = Taken(1, APPLE, 250, 1.25, "large")
    assert Taken.from_json(taken.as_json()) == taken


# --- giving back --------------------------------------------------------------------------------


def test_giving_back_after_the_unit_changed_keeps_the_items_grams_per_unit() -> None:
    """The user re-entered 400 g of oats as 4 cups meanwhile: 100 g back is one more cup."""
    taken = Taken(1, OATS, 100, 100, "g")
    assert give_back(400, 4, "cup", taken) == (500, 5)


def test_giving_back_to_an_emptied_item_whose_unit_changed_uses_the_conversion() -> None:
    taken = Taken(1, OATS, 100, 100, "g")
    assert give_back(0, 0, "cup", taken, grams_per_unit=80) == (100, 1.25)
    assert give_back(0, 0, "cup", taken, grams_per_unit=None) == (100, 0)
