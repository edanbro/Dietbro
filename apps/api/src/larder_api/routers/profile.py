"""The signed-in user's profile: goals, body stats, preferences, allergies; GDPR export/delete."""

from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_api.auth import CurrentUser
from larder_api.clock import Clock, get_clock
from larder_api.db import Session
from larder_api.demo import is_demo
from larder_api.routers.foods import summary
from larder_api.routers.pantry import expiring_count
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
    QuickNightsIn,
    RegionIn,
    RegionOption,
    RegionOut,
    SuggestedTargets,
)
from larder_api.settings import Settings, get_settings
from larder_core.allergens import LABELS, Allergen
from larder_core.brand import APP_NAME
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
from larder_core.regions import REGIONS, local_today, region_for, valid_timezone
from larder_db.models import (
    Allergies,
    Base,
    BodyProfile,
    BodyWeight,
    ChatThread,
    Craving,
    Food,
    Goals,
    LlmCall,
    MealLog,
    MealPlan,
    PantryItem,
    PlanTemplate,
    Preferences,
    PushSubscription,
    ReceiptUpload,
    Recipe,
    RecipeNote,
    ShareLink,
    ShoppingExtra,
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


async def _status(session: AsyncSession, user: User, today: date) -> ProfileStatus:
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
        expiring_soon=await expiring_count(session, user, today),
    )


@router.get("", operation_id="getMe")
async def get_me(
    user: CurrentUser, session: Session, clock: Annotated[Clock, Depends(get_clock)]
) -> Me:
    s = await _status(session, user, local_today(user.timezone, clock()))
    return Me(
        id=user.id,
        created_at=user.created_at,
        profile=s,
        setup_complete=s.has_goals and s.has_allergies and s.has_preferences,
        region=region_out(user),
    )


def region_out(user: User) -> RegionOut:
    r = region_for(user.country)
    return RegionOut(
        country=r.country,
        name=r.name,
        currency=r.currency,
        locale=user.locale or r.locale,
        timezone=user.timezone or r.timezone,
        saved=user.country is not None,
    )


@router.put("/region", operation_id="putRegion", responses=_PROBLEMS)
async def put_region(body: RegionIn, user: CurrentUser, session: Session) -> RegionOut:
    """Where the user lives: currency, price estimates, dates. Moving to a region with another
    currency also switches the goals' currency (the budget amount is kept)."""
    country = body.country.upper()
    if country not in REGIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, [f"{country} isn't supported yet."])
    if body.timezone is not None and not valid_timezone(body.timezone):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, [f"Unknown time zone {body.timezone}."])
    before = region_for(user.country).currency
    user.country = country
    user.timezone = body.timezone or user.timezone
    user.locale = body.locale or user.locale
    goals = await session.get(Goals, user.id)
    after = region_for(country).currency
    if goals is not None and after != before and goals.currency == before:
        goals.currency = after
    await session.commit()
    await session.refresh(user)
    return region_out(user)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteMe")
async def delete_me(
    user: CurrentUser, session: Session, settings: Annotated[Settings, Depends(get_settings)]
) -> Response:
    """Delete the account and all its data (GDPR). The identity-provider account is deleted
    by the client with its own SDK. The shared demo account can't be deleted."""
    if is_demo(user.auth_subject, settings.demo_auth_subject):
        raise HTTPException(status.HTTP_403_FORBIDDEN, ["The demo account can't be deleted."])
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

    def rows(objs: Iterable[Base], *exclude: str) -> list[dict[str, Any]]:
        return [row(o, *exclude) or {} for o in objs]

    pantry = await session.scalars(select(PantryItem).where(PantryItem.user_id == user.id))
    plans = await session.scalars(
        select(MealPlan)
        .where(MealPlan.user_id == user.id)
        .order_by(MealPlan.created_at)
        .options(selectinload(MealPlan.meals), selectinload(MealPlan.shopping))
    )
    threads = await session.scalars(
        select(ChatThread)
        .where(ChatThread.user_id == user.id)
        .order_by(ChatThread.created_at)
        .options(selectinload(ChatThread.messages))
    )
    recipes = await session.scalars(
        select(Recipe)
        .where(Recipe.owner_user_id == user.id)
        .order_by(Recipe.id)
        .options(selectinload(Recipe.ingredients))
    )
    cravings = await session.scalars(
        select(Craving).where(Craving.user_id == user.id).order_by(Craving.id)
    )
    logs = await session.scalars(
        select(MealLog).where(MealLog.user_id == user.id).order_by(MealLog.id)
    )
    calls = await session.scalars(
        select(LlmCall).where(LlmCall.user_id == user.id).order_by(LlmCall.id)
    )
    receipts = await session.scalars(
        select(ReceiptUpload)
        .where(ReceiptUpload.user_id == user.id)
        .order_by(ReceiptUpload.id)
        .options(selectinload(ReceiptUpload.lines))
    )

    response.headers["Content-Disposition"] = (
        f'attachment; filename="{APP_NAME.lower()}-export.json"'
    )
    return {
        "exported_at": datetime.now(UTC),
        "user": row(user),
        "goals": row(await session.get(Goals, user.id), "user_id"),
        "body": row(await session.get(BodyProfile, user.id), "user_id"),
        # Browsers reminders go to (their keys are left out: secrets of the browser).
        "push_subscriptions": rows(
            await session.scalars(
                select(PushSubscription)
                .where(PushSubscription.user_id == user.id)
                .order_by(PushSubscription.id)
            ),
            "user_id",
            "p256dh",
            "auth",
        ),
        # Public links the user made (recipe or week), revoked ones included.
        "share_links": rows(
            await session.scalars(
                select(ShareLink).where(ShareLink.user_id == user.id).order_by(ShareLink.id)
            ),
            "user_id",
        ),
        "recipe_notes": rows(
            await session.scalars(
                select(RecipeNote)
                .where(RecipeNote.user_id == user.id)
                .order_by(RecipeNote.recipe_id)
            ),
            "user_id",
        ),
        "plan_templates": rows(
            await session.scalars(
                select(PlanTemplate)
                .where(PlanTemplate.user_id == user.id)
                .order_by(PlanTemplate.id)
            ),
            "user_id",
        ),
        "weights": rows(
            await session.scalars(
                select(BodyWeight)
                .where(BodyWeight.user_id == user.id)
                .order_by(BodyWeight.measured_on)
            ),
            "user_id",
        ),
        "preferences": row(await session.get(Preferences, user.id), "user_id"),
        "allergies": row(await session.get(Allergies, user.id), "user_id"),
        "pantry": rows(pantry, "user_id"),
        "shopping_extras": rows(
            await session.scalars(
                select(ShoppingExtra)
                .where(ShoppingExtra.user_id == user.id)
                .order_by(ShoppingExtra.id)
            ),
            "user_id",
        ),
        "plans": [
            (row(p, "user_id") or {})
            | {"meals": rows(p.meals, "plan_id"), "shopping": rows(p.shopping, "plan_id")}
            for p in plans
        ],
        # Chat (M4): what was said (including the exact model transcript), the changes asked
        # for, food logged, model calls, and recipes drafted for the user.
        "threads": [
            (row(t, "user_id") or {}) | {"messages": rows(t.messages, "user_id", "thread_id")}
            for t in threads
        ],
        "cravings": rows(cravings, "user_id"),
        "meal_logs": rows(logs, "user_id"),
        "llm_calls": rows(calls, "user_id"),
        "recipes": [
            (row(r, "owner_user_id") or {}) | {"ingredients": rows(r.ingredients, "recipe_id")}
            for r in recipes
        ],
        # Pantry intake (M6): receipts and the lines read from them. A photo still waiting to
        # be read is not exported (it is deleted once read); its size and type are.
        "receipts": [
            (row(r, "user_id", "image") or {}) | {"lines": rows(r.lines, "upload_id")}
            for r in receipts
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
    return await _preferences_out(session, row) if row else None


@router.put("/preferences", operation_id="putPreferences")
async def put_preferences(
    body: PreferencesIn, user: CurrentUser, session: Session
) -> PreferencesOut:
    row = await session.get(Preferences, user.id) or Preferences(user_id=user.id)
    row.diet = body.diet
    row.liked_cuisines = sorted(set(body.liked_cuisines))
    row.disliked_cuisines = sorted(set(body.disliked_cuisines))
    row.liked_food_ids = await with_generics(session, body.liked_food_ids)
    row.disliked_food_ids = await with_generics(session, body.disliked_food_ids)
    session.add(row)
    await session.commit()
    return await _preferences_out(session, row)


@router.put(
    "/preferences/quick-nights",
    operation_id="putQuickNights",
    responses={409: {"model": Problems, "description": "preferences not set up yet"}},
)
async def put_quick_nights(
    body: QuickNightsIn, user: CurrentUser, session: Session
) -> PreferencesOut:
    """Busy nights: the weekdays whose dinner the planner keeps quick, and how quick."""
    row = await session.get(Preferences, user.id)
    if row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, ["Set your preferences first."])
    row.quick_days = sorted(set(body.days))
    row.quick_minutes = body.minutes
    await session.commit()
    return await _preferences_out(session, row)


async def _preferences_out(session: AsyncSession, row: Preferences) -> PreferencesOut:
    ids = {*row.liked_food_ids, *row.disliked_food_ids}
    foods = {f.id: f for f in await session.scalars(select(Food).where(Food.id.in_(ids)))}
    return PreferencesOut(
        diet=row.diet,  # pyright: ignore[reportArgumentType]
        liked_cuisines=row.liked_cuisines,
        disliked_cuisines=row.disliked_cuisines,
        liked_food_ids=row.liked_food_ids,
        disliked_food_ids=row.disliked_food_ids,
        liked_foods=[summary(foods[i]) for i in row.liked_food_ids if i in foods],
        disliked_foods=[summary(foods[i]) for i in row.disliked_food_ids if i in foods],
        quick_days=row.quick_days,
        quick_minutes=row.quick_minutes,
    )


async def with_generics(session: AsyncSession, food_ids: Iterable[int]) -> list[int]:
    """The foods plus the generic foods they count as: recipes use generic foods, so avoiding a
    regional or branded food ("Peanuts, plain" from CoFID) must avoid its generic too."""
    ids = set(food_ids)
    if ids:
        generics = await session.scalars(
            select(Food.generic_food_id).where(Food.id.in_(ids), Food.generic_food_id.is_not(None))
        )
        ids |= {g for g in generics if g is not None}
    return sorted(ids)


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
    row.avoid_food_ids = await with_generics(session, body.avoid_food_ids)
    session.add(row)
    await session.commit()
    return await _allergies_out(session, row)


@allergens_router.get("/cuisines", operation_id="listCuisines")
async def list_cuisines(session: Session) -> list[str]:
    """Cuisines of the shared catalogue (never of users' own recipes), for preference pickers."""
    rows = await session.scalars(
        select(Recipe.cuisine)
        .where(Recipe.cuisine.is_not(None), Recipe.owner_user_id.is_(None))
        .distinct()
        .order_by(Recipe.cuisine)
    )
    return [c for c in rows if c]


@allergens_router.get("/regions", operation_id="listRegions")
async def list_regions() -> list[RegionOption]:
    """Supported countries, by name."""
    return sorted(
        (
            RegionOption(country=r.country, name=r.name, currency=r.currency)
            for r in REGIONS.values()
        ),
        key=lambda o: o.name,
    )


@allergens_router.get("/allergens", operation_id="listAllergens")
async def list_allergens() -> list[AllergenOption]:
    return [AllergenOption(code=code, label=label) for code, label in LABELS.items()]
