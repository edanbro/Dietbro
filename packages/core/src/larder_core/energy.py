"""Energy needs and target safety (PLAN §8).

TDEE uses Mifflin-St Jeor BMR x an activity factor. Targets are refused when they go below the
user's calorie floor (never below HARD_FLOOR_KCAL), exceed a sane maximum, cut more than the
allowed daily deficit below TDEE, or ask for macros the energy band can't hold.
This is planning arithmetic, not medical advice; the UI says so.
"""

from dataclasses import dataclass
from enum import StrEnum

HARD_FLOOR_KCAL = 1000
DEFAULT_FLOOR_KCAL = 1200
DEFAULT_MAX_DEFICIT_KCAL = 1000
MAX_DEFICIT_LIMIT_KCAL = 1500
MAX_KCAL = 6000
MIN_AGE = 18


class Sex(StrEnum):
    FEMALE = "female"
    MALE = "male"


class Activity(StrEnum):
    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    ACTIVE = "active"
    VERY_ACTIVE = "very_active"


ACTIVITY_FACTOR: dict[Activity, float] = {
    Activity.SEDENTARY: 1.2,
    Activity.LIGHT: 1.375,
    Activity.MODERATE: 1.55,
    Activity.ACTIVE: 1.725,
    Activity.VERY_ACTIVE: 1.9,
}


class Goal(StrEnum):
    LOSE = "lose"
    MAINTAIN = "maintain"
    GAIN = "gain"


@dataclass(frozen=True, slots=True)
class Body:
    sex: Sex
    age: int
    height_cm: float
    weight_kg: float
    activity: Activity


@dataclass(frozen=True, slots=True)
class Targets:
    """Daily bands. Macro bounds are optional (None = unconstrained)."""

    kcal_min: float
    kcal_max: float
    calorie_floor: float = DEFAULT_FLOOR_KCAL
    max_daily_deficit: float = DEFAULT_MAX_DEFICIT_KCAL
    protein_g_min: float | None = None
    protein_g_max: float | None = None
    fat_g_min: float | None = None
    fat_g_max: float | None = None
    carbs_g_min: float | None = None
    carbs_g_max: float | None = None


def bmr(body: Body) -> float:
    base = 10 * body.weight_kg + 6.25 * body.height_cm - 5 * body.age
    return base + 5 if body.sex is Sex.MALE else base - 161


def tdee(body: Body) -> float:
    return bmr(body) * ACTIVITY_FACTOR[body.activity]


def validate_body(body: Body) -> list[str]:
    problems: list[str] = []
    if not MIN_AGE <= body.age <= 110:
        problems.append(f"age must be between {MIN_AGE} and 110")
    if not 120 <= body.height_cm <= 250:
        problems.append("height must be between 120 and 250 cm")
    if not 30 <= body.weight_kg <= 350:
        problems.append("weight must be between 30 and 350 kg")
    return problems


def validate_targets(t: Targets, tdee_kcal: float | None = None) -> list[str]:
    """Human-readable problems; empty means the targets are acceptable."""
    problems: list[str] = []
    if t.calorie_floor < HARD_FLOOR_KCAL:
        problems.append(f"calorie floor can't be below {HARD_FLOOR_KCAL} kcal")
    if t.kcal_min < max(t.calorie_floor, HARD_FLOOR_KCAL):
        problems.append(f"daily minimum is below your calorie floor ({t.calorie_floor:.0f} kcal)")
    if t.kcal_min > t.kcal_max:
        problems.append("daily minimum is above the daily maximum")
    if t.kcal_max > MAX_KCAL:
        problems.append(f"daily maximum can't exceed {MAX_KCAL} kcal")
    if not 0 <= t.max_daily_deficit <= MAX_DEFICIT_LIMIT_KCAL:
        problems.append(f"max daily deficit must be between 0 and {MAX_DEFICIT_LIMIT_KCAL} kcal")
    elif tdee_kcal is not None and t.kcal_min < tdee_kcal - t.max_daily_deficit:
        problems.append(
            f"daily minimum is more than {t.max_daily_deficit:.0f} kcal below your estimated "
            f"needs ({tdee_kcal:.0f} kcal); that deficit is too large"
        )
    for name, lo, hi in (
        ("protein", t.protein_g_min, t.protein_g_max),
        ("fat", t.fat_g_min, t.fat_g_max),
        ("carbs", t.carbs_g_min, t.carbs_g_max),
    ):
        if (lo is not None and lo < 0) or (hi is not None and hi < 0):
            problems.append(f"{name} bounds can't be negative")
        if lo is not None and hi is not None and lo > hi:
            problems.append(f"{name} minimum is above its maximum")
    macro_floor_kcal = (
        4 * (t.protein_g_min or 0) + 9 * (t.fat_g_min or 0) + 4 * (t.carbs_g_min or 0)
    )
    if macro_floor_kcal > t.kcal_max:
        problems.append(
            f"macro minimums need {macro_floor_kcal:.0f} kcal, more than the daily maximum"
        )
    return problems


# Suggested change from maintenance energy, and band half-width.
_GOAL_OFFSET_KCAL = {Goal.LOSE: -450.0, Goal.MAINTAIN: 0.0, Goal.GAIN: 300.0}
_BAND_KCAL = 100.0
_PROTEIN_G_PER_KG = 1.2


def suggest_targets(body: Body, goal: Goal) -> Targets:
    """A conservative starting point the user can adjust; always passes validate_targets."""
    need = tdee(body)
    centre = need + _GOAL_OFFSET_KCAL[goal]
    kcal_min = max(centre - _BAND_KCAL, DEFAULT_FLOOR_KCAL, need - DEFAULT_MAX_DEFICIT_KCAL)
    kcal_max = min(max(centre + _BAND_KCAL, kcal_min + _BAND_KCAL), MAX_KCAL)
    kcal_min = min(kcal_min, kcal_max)
    protein = round(body.weight_kg * _PROTEIN_G_PER_KG, 1)
    protein = min(protein, kcal_max * 0.35 / 4)  # keep the macro floor inside the band
    return Targets(kcal_min=round(kcal_min), kcal_max=round(kcal_max), protein_g_min=protein)
