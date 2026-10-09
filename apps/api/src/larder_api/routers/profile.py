"""The signed-in user's profile: goals, body stats, preferences, allergies; GDPR export/delete."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_api.auth import CurrentUser
from larder_api.db import Session
from larder_api.routers.foods import summary
from larder_api.schemas import (
    AllergenOption,
    AllergiesIn,
    AllergiesOut,
    BodyIn,
    BodyOut,
    GoalsIn,
    GoalsOut,
    Me,
    PreferencesIn,
    PreferencesOut,
    Problems,
    ProfileStatus,
    SuggestedTargets,
)
from larder_core.allergens import LABELS, Allergen
from larder_core.energy import (
    Activity,
    Body,
    Goal,
    Sex,
    Targets,
    suggest_targets,
    tdee,
    validate_body,
    validate_targets,
)
from larder_db.models import (
    Allergies,
    Base,
    BodyProfile,
    Food,
    Goals,
    MealPlan,
    PantryItem,
    Preferences,
    Recipe,
    User,
)

router = APIRouter(prefix="/me", tags=["profile"])
allergens_router = APIRouter(tags=["profile"])

_PROBLEMS: dict[int | str, dict[str, Any]] = {status.HTTP_400_BAD_REQUEST: {"model": Problems}}


def _year() -> int:
    return datetime.now(UTC).year


def body_from_row(row: BodyProfile) -> Body:
    return Body(
        sex=Sex(row.sex),
        age=_year() - row.birth_year,
        height_cm=row.height_cm,
        weight_kg=row.weight_kg,
        activity=Activity(row.activity),
    )


def _body_out(row: BodyProfile) -> BodyOut:
    body = body_from_row(row)
    suggestions = {
        goal: SuggestedTargets(
            kcal_min=t.kcal_min, kcal_max=t.kcal_max, protein_g_min=t.protein_g_min
        )
        for goal in Goal
        for t in [suggest_targets(body, goal)]
    }
    return BodyOut(
        sex=body.sex,
        age=body.age,
        height_cm=body.height_cm,
        weight_kg=body.weight_kg,
        activity=body.activity,
        tdee_kcal=round(tdee(body)),
        suggestions=suggestions,
    )


async def _status(session: AsyncSession, user: User) -> ProfileStatus:
    async def has(model: type[Goals | BodyProfile | Allergies | Preferences]) -> bool:
        return await session.get(model, user.id) is not None

    pantry = await session.scalar(
        select(func.count(PantryItem.id)).where(PantryItem.user_id == user.id)
    )
    return ProfileStatus(
        has_goals=await has(Goals),
        has_body=await has(BodyProfile),
        has_allergies=await has(Allergies),
        has_preferences=await has(Preferences),
        pantry_items=pantry or 0,
    )


@router.get("", operation_id="getMe")
async def get_me(user: CurrentUser, session: Session) -> Me:
    s = await _status(session, user)
    return Me(
        id=user.id,
        created_at=user.created_at,
        profile=s,
        setup_complete=s.has_goals and s.has_allergies and s.has_preferences,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteMe")
async def delete_me(user: CurrentUser, session: Session) -> Response:
    """Delete the account and all its data (GDPR). The identity-provider account is deleted
    by the client with its own SDK."""
    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/export", operation_id="exportMe")
async def export_me(user: CurrentUser, session: Session, response: Response) -> dict[str, Any]:
    """Everything stored about the user, as JSON (GDPR data portability)."""

    def row(obj: Base | None, *exclude: str) -> dict[str, Any] | None:
        if obj is None:
            return None
        attrs = inspect(obj).mapper.column_attrs
        return {a.key: getattr(obj, a.key) for a in attrs if a.key not in exclude}

    pantry = await session.scalars(select(PantryItem).where(PantryItem.user_id == user.id))
    plans = await session.scalars(
        select(MealPlan)
        .where(MealPlan.user_id == user.id)
        .order_by(MealPlan.created_at)
        .options(selectinload(MealPlan.meals), selectinload(MealPlan.shopping))
    )
    response.headers["Content-Disposition"] = 'attachment; filename="larder-export.json"'
    return {
        "exported_at": datetime.now(UTC),
        "user": row(user),
        "goals": row(await session.get(Goals, user.id), "user_id"),
        "body": row(await session.get(BodyProfile, user.id), "user_id"),
        "preferences": row(await session.get(Preferences, user.id), "user_id"),
        "allergies": row(await session.get(Allergies, user.id), "user_id"),
        "pantry": [row(p, "user_id") for p in pantry],
        "plans": [
            (row(p, "user_id") or {})
            | {
                "meals": [row(m, "plan_id") for m in p.meals],
                "shopping": [row(s, "plan_id") for s in p.shopping],
            }
            for p in plans
        ],
    }


@router.get("/goals", operation_id="getGoals")
async def get_goals(user: CurrentUser, session: Session) -> GoalsOut | None:
    goals = await session.get(Goals, user.id)
    return GoalsOut.model_validate(goals) if goals else None


@router.put("/goals", operation_id="putGoals", responses=_PROBLEMS)
async def put_goals(body: GoalsIn, user: CurrentUser, session: Session) -> GoalsOut:
    """Refuses unsafe or impossible targets (calorie floor, max deficit vs estimated needs)."""
    stats = await session.get(BodyProfile, user.id)
    targets = Targets(
        **body.model_dump(exclude={"goal", "weekly_budget_minor", "currency"}),
    )
    problems = validate_targets(targets, tdee(body_from_row(stats)) if stats else None)
    if problems:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problems)
    goals = await session.get(Goals, user.id) or Goals(user_id=user.id)
    for key, value in body.model_dump().items():
        setattr(goals, key, value)
    session.add(goals)
    await session.commit()
    await session.refresh(goals)
    return GoalsOut.model_validate(goals)


@router.get("/body", operation_id="getBody")
async def get_body(user: CurrentUser, session: Session) -> BodyOut | None:
    row = await session.get(BodyProfile, user.id)
    return _body_out(row) if row else None


@router.put("/body", operation_id="putBody", responses=_PROBLEMS)
async def put_body(body: BodyIn, user: CurrentUser, session: Session) -> BodyOut:
    problems = validate_body(
        Body(body.sex, body.age, body.height_cm, body.weight_kg, body.activity)
    )
    if problems:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problems)
    row = await session.get(BodyProfile, user.id) or BodyProfile(user_id=user.id)
    row.sex = body.sex
    row.birth_year = _year() - body.age
    row.height_cm = body.height_cm
    row.weight_kg = body.weight_kg
    row.activity = body.activity
    session.add(row)
    await session.commit()
    return _body_out(row)


@router.delete("/body", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteBody")
async def delete_body(user: CurrentUser, session: Session) -> Response:
    await session.execute(delete(BodyProfile).where(BodyProfile.user_id == user.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/preferences", operation_id="getPreferences")
async def get_preferences(user: CurrentUser, session: Session) -> PreferencesOut | None:
    row = await session.get(Preferences, user.id)
    return PreferencesOut.model_validate(row) if row else None


@router.put("/preferences", operation_id="putPreferences")
async def put_preferences(
    body: PreferencesIn, user: CurrentUser, session: Session
) -> PreferencesOut:
    row = await session.get(Preferences, user.id) or Preferences(user_id=user.id)
    row.diet = body.diet
    row.liked_cuisines = sorted(set(body.liked_cuisines))
    row.disliked_cuisines = sorted(set(body.disliked_cuisines))
    row.liked_food_ids = sorted(set(body.liked_food_ids))
    row.disliked_food_ids = sorted(set(body.disliked_food_ids))
    session.add(row)
    await session.commit()
    return PreferencesOut.model_validate(row)


async def _allergies_out(session: AsyncSession, row: Allergies) -> AllergiesOut:
    foods = await session.scalars(select(Food).where(Food.id.in_(row.avoid_food_ids)))
    return AllergiesOut(
        allergens=[Allergen(a) for a in row.allergens],
        avoid_food_ids=row.avoid_food_ids,
        avoid_foods=[summary(f) for f in foods],
    )


@router.get("/allergies", operation_id="getAllergies")
async def get_allergies(user: CurrentUser, session: Session) -> AllergiesOut | None:
    row = await session.get(Allergies, user.id)
    return await _allergies_out(session, row) if row else None


@router.put("/allergies", operation_id="putAllergies")
async def put_allergies(body: AllergiesIn, user: CurrentUser, session: Session) -> AllergiesOut:
    """Hard constraints: no planned recipe will contain these (enforced by the solver, M3)."""
    row = await session.get(Allergies, user.id) or Allergies(user_id=user.id)
    row.allergens = sorted({a.value for a in body.allergens})
    row.avoid_food_ids = sorted(set(body.avoid_food_ids))
    session.add(row)
    await session.commit()
    return await _allergies_out(session, row)


@allergens_router.get("/cuisines", operation_id="listCuisines")
async def list_cuisines(session: Session) -> list[str]:
    """Cuisines of the seeded recipes, for preference pickers."""
    rows = await session.scalars(
        select(Recipe.cuisine)
        .where(Recipe.cuisine.is_not(None))
        .distinct()
        .order_by(Recipe.cuisine)
    )
    return [c for c in rows if c]


@allergens_router.get("/allergens", operation_id="listAllergens")
async def list_allergens() -> list[AllergenOption]:
    return [AllergenOption(code=code, label=label) for code, label in LABELS.items()]
