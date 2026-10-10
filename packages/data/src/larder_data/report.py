"""Resolution metrics for the M1 acceptance check (>= 95% of ingredient lines -> USDA food), and
which recipes the planner may use (docs/adr/0010-meal-slots-and-curated-recipes.md)."""

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from larder_core.meals import (
    MAX_KCAL_PER_SERVING,
    MAX_OIL_SHARE,
    SLOT_ORDER,
    load_overrides,
    recipe_slots,
)
from larder_core.names import normalise_name
from larder_db.models import Food, Recipe, RecipeIngredient


@dataclass(frozen=True, slots=True)
class Report:
    lines: int
    lines_with_food: int
    lines_with_grams: int
    recipes: int
    recipes_complete: int
    by_method: dict[str, int]
    unmatched: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])
    no_grams: list[tuple[str, str, int]] = field(default_factory=list[tuple[str, str, int]])
    # Planning: recipes per slot, and complete recipes the planner won't use (name, reason).
    per_slot: dict[str, int] = field(default_factory=dict[str, int])
    excluded: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

    @property
    def food_coverage(self) -> float:
        return self.lines_with_food / self.lines if self.lines else 0.0

    @property
    def grams_coverage(self) -> float:
        return self.lines_with_grams / self.lines if self.lines else 0.0

    @property
    def recipe_coverage(self) -> float:
        return self.recipes_complete / self.recipes if self.recipes else 0.0


async def build_report(session: AsyncSession, top: int = 25) -> Report:
    rows = (
        await session.execute(
            select(
                RecipeIngredient.raw_name,
                RecipeIngredient.raw_measure,
                RecipeIngredient.food_id,
                RecipeIngredient.grams,
                RecipeIngredient.match_method,
            )
        )
    ).all()
    recipes = await session.scalar(select(func.count(Recipe.id))) or 0
    complete = (
        await session.scalar(select(func.count(Recipe.id)).where(Recipe.nutrition_complete)) or 0
    )
    per_slot, excluded = await planning_eligibility(session)
    unmatched = Counter(normalise_name(r[0]) for r in rows if r[2] is None)
    no_grams = Counter((normalise_name(r[0]), r[1].lower()) for r in rows if r[2] and r[3] is None)
    return Report(
        lines=len(rows),
        lines_with_food=sum(1 for r in rows if r[2] is not None),
        lines_with_grams=sum(1 for r in rows if r[3] is not None),
        recipes=recipes,
        recipes_complete=complete,
        by_method=dict(Counter(r[4] or "unmatched" for r in rows)),
        unmatched=unmatched.most_common(top),
        no_grams=[(n, m, c) for (n, m), c in no_grams.most_common(top)],
        per_slot=per_slot,
        excluded=excluded,
    )


async def planning_eligibility(
    session: AsyncSession,
) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """Plannable recipes per slot, and complete recipes excluded or reclassified, with why."""
    recipes = (
        await session.scalars(
            select(Recipe)
            .where(Recipe.nutrition_complete)
            .options(selectinload(Recipe.ingredients))
            .order_by(Recipe.source, Recipe.name)
        )
    ).all()
    oils = set(await session.scalars(select(Food.id).where(Food.category == "Fats and Oils")))
    overrides = load_overrides()
    per_slot: Counter[str] = Counter()
    excluded: list[tuple[str, str]] = []
    for r in recipes:
        total = sum(i.grams or 0.0 for i in r.ingredients)
        oil = sum(i.grams or 0.0 for i in r.ingredients if i.food_id in oils)
        share = oil / total if total else 0.0
        slots = recipe_slots(r.source, r.source_id, r.category, r.kcal, share)
        per_slot.update(s.value for s in slots)
        if (o := overrides.get((r.source, r.source_id))) is not None:
            where = ", ".join(sorted(o.slots)) + " only" if o.slots else "not planned"
            excluded.append((r.name, f"{where} (reviewed: {o.note.split(': ', 1)[-1]})"))
        elif not slots and (r.kcal or 0) > MAX_KCAL_PER_SERVING:
            excluded.append((r.name, f"{r.kcal:,.0f} kcal per serving"))
        elif not slots and share > MAX_OIL_SHARE:
            excluded.append((r.name, f"oil is {100 * share:.0f}% of the recipe"))
    return {s.value: per_slot[s.value] for s in SLOT_ORDER}, excluded


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render(r: Report) -> str:
    lines = [
        "# Ingredient resolution report",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Ingredient lines | {r.lines} |",
        f"| Lines resolved to a USDA food | {r.lines_with_food} ({pct(r.food_coverage)}) |",
        f"| Lines with a gram weight | {r.lines_with_grams} ({pct(r.grams_coverage)}) |",
        f"| Recipes | {r.recipes} |",
        f"| Recipes with complete nutrition | {r.recipes_complete} ({pct(r.recipe_coverage)}) |",
        "",
        "Lines by match method: "
        + ", ".join(f"{k} {v}" for k, v in sorted(r.by_method.items(), key=lambda kv: -kv[1])),
        "",
        "## Most frequent unmatched names",
        "",
        *(f"- {name} ({count})" for name, count in r.unmatched),
        "",
        "## Most frequent matched lines without grams",
        "",
        *(f"- {name}: `{measure}` ({count})" for name, measure, count in r.no_grams),
        "",
        "## Planning",
        "",
        "Plannable recipes per slot: "
        + ", ".join(f"{slot} {count}" for slot, count in r.per_slot.items()),
        "",
        "Complete recipes the planner won't use, or uses only in some slots:",
        "",
        *(f"- {name}: {why}" for name, why in r.excluded),
        "",
    ]
    return "\n".join(lines)
