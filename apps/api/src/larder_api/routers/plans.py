"""Weekly plans: generate (solve + validate + persist), read, and the shopping list.

Every query is filtered by the signed-in user; other users' plans are 404s.
"""

from typing import Any

from fastapi import APIRouter, status

from larder_api.auth import CurrentUser
from larder_api.db import Session
from larder_api.schemas import (
    PlanOut,
    PlanRequest,
    Problems,
    ShoppingItemOut,
    ShoppingItemPatch,
    ShoppingListOut,
)

router = APIRouter(prefix="/plans", tags=["plans"])

_CREATE_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: {
        "model": Problems,
        "description": "bad start date, or no plan fits (reasons)",
    },
    status.HTTP_409_CONFLICT: {
        "model": Problems,
        "description": "setup incomplete (goals, allergies, preferences) or goals need review",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": Problems,
        "description": "the planner found no plan in time",
    },
}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    operation_id="createPlan",
    responses=_CREATE_ERRORS,
)
async def create_plan(body: PlanRequest, user: CurrentUser, session: Session) -> PlanOut:
    raise NotImplementedError


@router.get("/current", operation_id="getCurrentPlan")
async def current_plan(user: CurrentUser, session: Session) -> PlanOut | None:
    """The most recently created plan, or null if there is none."""
    raise NotImplementedError


@router.get("/{plan_id}", operation_id="getPlan")
async def get_plan(plan_id: int, user: CurrentUser, session: Session) -> PlanOut:
    raise NotImplementedError


@router.get("/{plan_id}/shopping", operation_id="getShoppingList")
async def shopping_list(plan_id: int, user: CurrentUser, session: Session) -> ShoppingListOut:
    raise NotImplementedError


@router.patch("/{plan_id}/shopping/{food_id}", operation_id="patchShoppingItem")
async def patch_shopping_item(
    plan_id: int, food_id: int, body: ShoppingItemPatch, user: CurrentUser, session: Session
) -> ShoppingItemOut:
    raise NotImplementedError
