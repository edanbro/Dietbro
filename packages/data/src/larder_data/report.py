"""Resolution metrics for the M1 acceptance check (>= 95% of ingredient lines -> USDA food)."""

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from larder_data.text import normalise_name
from larder_db.models import Recipe, RecipeIngredient


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
    )


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
    ]
    return "\n".join(lines)
