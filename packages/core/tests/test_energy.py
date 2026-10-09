import pytest
from hypothesis import given
from hypothesis import strategies as st

from larder_core.energy import (
    HARD_FLOOR_KCAL,
    Activity,
    Body,
    Goal,
    Sex,
    Targets,
    bmr,
    suggest_targets,
    tdee,
    validate_body,
    validate_targets,
)

bodies = st.builds(
    Body,
    sex=st.sampled_from(Sex),
    age=st.integers(min_value=18, max_value=100),
    height_cm=st.floats(min_value=130, max_value=220),
    weight_kg=st.floats(min_value=40, max_value=250),
    activity=st.sampled_from(Activity),
)


def test_mifflin_st_jeor_reference_values() -> None:
    # 30-year-old, 180 cm, 80 kg: 10*80 + 6.25*180 - 5*30 = 1775; +5 male / -161 female.
    assert bmr(Body(Sex.MALE, 30, 180, 80, Activity.SEDENTARY)) == pytest.approx(1780)
    assert bmr(Body(Sex.FEMALE, 30, 180, 80, Activity.SEDENTARY)) == pytest.approx(1614)
    assert tdee(Body(Sex.MALE, 30, 180, 80, Activity.MODERATE)) == pytest.approx(1780 * 1.55)


@given(bodies, st.floats(min_value=0.5, max_value=20))
def test_bmr_grows_with_weight_and_falls_with_age(body: Body, delta: float) -> None:
    heavier = Body(body.sex, body.age, body.height_cm, body.weight_kg + delta, body.activity)
    assert bmr(heavier) > bmr(body)
    if body.age < 100:
        older = Body(body.sex, body.age + 1, body.height_cm, body.weight_kg, body.activity)
        assert bmr(older) < bmr(body)


@given(bodies)
def test_tdee_is_at_least_bmr(body: Body) -> None:
    assert tdee(body) >= bmr(body)


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        (Body(Sex.FEMALE, 15, 160, 50, Activity.LIGHT), "age"),
        (Body(Sex.FEMALE, 30, 90, 50, Activity.LIGHT), "height"),
        (Body(Sex.FEMALE, 30, 160, 20, Activity.LIGHT), "weight"),
    ],
)
def test_validate_body(body: Body, problem: str) -> None:
    problems = validate_body(body)
    assert len(problems) == 1
    assert problem in problems[0]


def test_valid_targets_have_no_problems() -> None:
    assert validate_targets(Targets(kcal_min=1800, kcal_max=2200)) == []


@pytest.mark.parametrize(
    ("targets", "tdee_kcal", "problem"),
    [
        (Targets(kcal_min=900, kcal_max=1100, calorie_floor=900), None, "floor"),
        (Targets(kcal_min=1100, kcal_max=1500), None, "below your calorie floor"),
        (Targets(kcal_min=2200, kcal_max=1800), None, "minimum"),
        (Targets(kcal_min=2000, kcal_max=9000), None, "maximum"),
        (Targets(kcal_min=1300, kcal_max=1500), 2600, "deficit"),
        (Targets(kcal_min=1800, kcal_max=2000, max_daily_deficit=2000), None, "deficit"),
        (
            Targets(kcal_min=1800, kcal_max=2000, protein_g_min=200, protein_g_max=100),
            None,
            "protein",
        ),
        (Targets(kcal_min=1500, kcal_max=1600, protein_g_min=300, fat_g_min=100), None, "macro"),
    ],
)
def test_validate_targets_refuses_unsafe_or_impossible(
    targets: Targets, tdee_kcal: float | None, problem: str
) -> None:
    problems = validate_targets(targets, tdee_kcal)
    assert any(problem in p for p in problems), problems


def test_hard_floor_cannot_be_configured_away() -> None:
    assert validate_targets(Targets(kcal_min=800, kcal_max=900, calorie_floor=800))
    assert HARD_FLOOR_KCAL == 1000


@given(bodies, st.sampled_from(Goal))
def test_suggestions_are_always_valid(body: Body, goal: Goal) -> None:
    targets = suggest_targets(body, goal)
    assert validate_targets(targets, tdee(body)) == []
    assert targets.kcal_min <= targets.kcal_max


def test_weight_loss_suggestion_is_a_moderate_deficit() -> None:
    body = Body(Sex.MALE, 30, 180, 80, Activity.MODERATE)  # TDEE ~2759
    t = suggest_targets(body, Goal.LOSE)
    assert 2759 - 600 < t.kcal_min < t.kcal_max < 2759
    assert t.protein_g_min == pytest.approx(80 * 1.2)
