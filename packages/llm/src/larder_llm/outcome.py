"""What applying plan changes did, in plain values: the API's executor returns this and the
client gets it as the replan response. No database or solver types here."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from larder_core.meals import Slot

type ChangeStatus = Literal["applied", "unchanged", "failed"]
type ChangeReason = Literal["craving", "swap", "skip", "ate_off_plan", "rebalance", "resize"]


class ChangeResult(BaseModel):
    """One requested change (by its position in the request) and what became of it."""

    index: int
    intent: Literal["craving", "ate_off_plan", "skip", "swap"]
    date: date
    slot: Slot | None
    status: ChangeStatus  # unchanged = already done (same change earlier) or nothing to do
    message: str  # user-facing: "Thursday dinner is now Chilli con carne." / why it failed
    recipe_id: int | None = None
    recipe_name: str | None = None


class SlotChange(BaseModel):
    """One meal that differs between the parent and the new plan version (recipe or size)."""

    date: date
    slot: Slot
    before: str | None  # recipe name; None = no meal
    after: str | None
    after_recipe_id: int | None = None
    before_portions: int | None = None  # half-servings
    after_portions: int | None = None
    change_index: int | None = None  # the ChangeResult that caused it; None = rebalance/resize
    reason: ChangeReason


class Logged(BaseModel):
    """Food recorded as eaten off-plan, a skipped meal (counted as eaten elsewhere or not), or a
    planned meal marked eaten from the plan screen."""

    date: date
    slot: Slot | None
    kind: Literal["off_plan", "skipped", "eaten"]
    description: str
    kcal: int
    estimated: bool = True  # always an estimate unless every item matched with an exact amount


class DayKcal(BaseModel):
    """A changed day's new total against the band it was planned to."""

    date: date
    kcal: int
    min: int
    max: int
    floor: int
    relaxed: bool  # the band was widened for this day because of what the user reported
    within: bool  # kcal inside the user's normal band (min..max)


class ReplanOutcome(BaseModel):
    """Result of one request_replan (or one offline action). `plan_id` is the new version, or
    None when nothing was saved. Facts (logs) are recorded even when no version is saved."""

    plan_id: int | None = None
    version: int | None = None
    fresh: bool = False  # a new week was started because no plan covered the dates
    results: list[ChangeResult] = Field(default_factory=list[ChangeResult])
    changes: list[SlotChange] = Field(default_factory=list[SlotChange])
    logged: list[Logged] = Field(default_factory=list[Logged])
    days: list[DayKcal] = Field(default_factory=list[DayKcal])
    # Hard rules the saved plan still misses from today on (baseline planner only), in words.
    warnings: list[str] = Field(default_factory=list[str])
    notes: list[str] = Field(default_factory=list[str])  # "I took that as dinner."
