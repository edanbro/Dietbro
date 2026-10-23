"""Plan templates: a week of meals saved by name, to plan from again (POST /plans with
`template_id`). Saving copies the meals' recipes and slots; planning from a template checks
every recipe again against the user's allergies, diet and blocks as they are then."""

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from larder_api.auth import CurrentUser
from larder_api.db import Session
from larder_api.schemas import TemplateIn, TemplateOut, TemplatePatch
from larder_core.meals import SLOT_ORDER, Slot
from larder_db.models import MealPlan, PlanTemplate, Recipe

router = APIRouter(prefix="/me/templates", tags=["templates"])

MAX_TEMPLATES = 20
PREVIEW = 4  # recipe names shown per template


async def _out(session: Session, rows: list[PlanTemplate]) -> list[TemplateOut]:
    ids = {int(c["recipe_id"]) for t in rows for c in t.cells}
    names = {
        rid: name
        for rid, name in await session.execute(
            select(Recipe.id, Recipe.name).where(Recipe.id.in_(ids))
        )
    }
    out: list[TemplateOut] = []
    for t in rows:
        # Dinners first: they say most about a week.
        cells = sorted(t.cells, key=lambda c: (Slot(c["slot"]) != Slot.DINNER, int(c["day"])))
        preview = list(dict.fromkeys(names.get(int(c["recipe_id"]), "") for c in cells))
        out.append(
            TemplateOut(
                id=t.id,
                name=t.name,
                created_at=t.created_at,
                meals=len(t.cells),
                recipes=[n for n in preview if n][:PREVIEW],
            )
        )
    return out


async def _own(session: Session, user_id: int, template_id: int) -> PlanTemplate:
    row = await session.scalar(
        select(PlanTemplate).where(PlanTemplate.id == template_id, PlanTemplate.user_id == user_id)
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, ["That template doesn't exist."])
    return row


@router.get("", operation_id="listTemplates")
async def list_templates(user: CurrentUser, session: Session) -> list[TemplateOut]:
    rows = list(
        await session.scalars(
            select(PlanTemplate)
            .where(PlanTemplate.user_id == user.id)
            .order_by(PlanTemplate.created_at.desc(), PlanTemplate.id.desc())
        )
    )
    return await _out(session, rows)


@router.post("", status_code=status.HTTP_201_CREATED, operation_id="saveTemplate")
async def save_template(body: TemplateIn, user: CurrentUser, session: Session) -> TemplateOut:
    """Save the meals of the user's plan starting on `start` (its newest version)."""
    count = await session.scalar(
        select(func.count(PlanTemplate.id)).where(PlanTemplate.user_id == user.id)
    )
    if (count or 0) >= MAX_TEMPLATES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            [f"You have {MAX_TEMPLATES} templates already. Delete one to save another."],
        )
    plan = await session.scalar(
        select(MealPlan)
        .where(MealPlan.user_id == user.id, MealPlan.start_date == body.start)
        .order_by(MealPlan.version.desc())
        .limit(1)
        .options(selectinload(MealPlan.meals))
    )
    if plan is None or not plan.meals:
        raise HTTPException(status.HTTP_404_NOT_FOUND, ["There's no plan for that week."])
    meals = sorted(plan.meals, key=lambda m: (m.day, SLOT_ORDER.index(Slot(m.slot))))
    row = PlanTemplate(
        user_id=user.id,
        name=body.name.strip(),
        cells=[{"day": m.day, "slot": m.slot, "recipe_id": m.recipe_id} for m in meals],
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return (await _out(session, [row]))[0]


@router.patch("/{template_id}", operation_id="renameTemplate")
async def rename_template(
    template_id: int, body: TemplatePatch, user: CurrentUser, session: Session
) -> TemplateOut:
    row = await _own(session, user.id, template_id)
    row.name = body.name.strip()
    await session.commit()
    await session.refresh(row)
    return (await _out(session, [row]))[0]


@router.delete(
    "/{template_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteTemplate"
)
async def delete_template(template_id: int, user: CurrentUser, session: Session) -> Response:
    row = await _own(session, user.id, template_id)
    await session.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
