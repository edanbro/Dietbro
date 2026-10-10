"""What applying plan changes did, in plain values: the API's executor returns this, the agent
sees it as a tool result (JSON), and the offline path turns it into a reply with
`larder_llm.reply.offline_reply`. No database or solver types here."""

from datetime import date

from pydantic import BaseModel, Field

from larder_core.meals import Slot


class SlotChange(BaseModel):
    """One meal that differs between the old and the new plan version."""

    date: date
    slot: Slot
    before: str | None  # recipe name, None = no meal
    after: str | None
    after_recipe_id: int | None = None
    reason: str  # "craving" | "skip" | "ate_off_plan" | "swap" | "rebalance"


class Logged(BaseModel):
    """Food recorded as eaten off-plan (or a skipped meal counted as eaten elsewhere)."""

    date: date
    slot: Slot | None
    description: str
    kcal: int
    estimated: bool = True  # always an estimate unless the user gave exact foods and grams


class ReplanOutcome(BaseModel):
    """Result of one request_replan / offline action. `plan_id` is the new version, or None
    when nothing was saved (every change failed, or nothing needed to change)."""

    plan_id: int | None = None
    version: int | None = None
    changes: list[SlotChange] = Field(default_factory=list[SlotChange])
    logged: list[Logged] = Field(default_factory=list[Logged])
    # One line per change that could not be applied, in user-facing words ("No safe spicy
    # dinner fits Thursday's calories; I kept your plan.").
    failures: list[str] = Field(default_factory=list[str])
    notes: list[str] = Field(default_factory=list[str])
    day_kcal: dict[date, int] = Field(default_factory=dict[date, int])  # new totals, changed days
