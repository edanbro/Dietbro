"""create_recipe: a drafted recipe -> a private, validated recipe row, or the problems to fix.

1. Each ingredient: quantity parsed (larder_core.units, grams via the food's portions) and name
   matched (foods.match_food). Unmatched or unparseable -> a problem ("couldn't match 'X' - use a
   common ingredient name"); store-cupboard staples (salt, pepper, water, dried herbs) may be
   unquantified.
2. Build the row (source="generated", owner_user_id=user, servings, category from the slot)
   and run the same path the planner uses: planning.recipe_facts -> solver Recipe + foods. The
   gate is exactly the planner's: `candidates.allowed(recipe, foods, profile)` and `slot in
   facts.slots` (kcal per serving, oil share). For a restricted user any line that isn't an
   exact curated match counts as unresolved, so `allowed` rejects it - report "couldn't verify
   'X' against your allergies; use a common ingredient name". Never add a separate notion of a
   trusted match.
3. Also reject when the name or instructions mention, as a whole word, an avoided food's name
   or alias, or an allergen word for the user's allergens (the tagger's text rules).
4. Nutrition from USDA data only. Save (nutrition_complete=True), commit before returning so a
   request_replan in the same turn (its own session) can use the id.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_api.chat import foods
from larder_api.chat.foods import tokens
from larder_api.chat.scope import ChatScope
from larder_core.aliases import load_alias_rows
from larder_core.allergens import Allergen
from larder_core.cook_time import cook_minutes
from larder_core.meals import (
    MAX_KCAL_PER_SERVING,
    MAX_OIL_SHARE,
    MAX_SODIUM_MG_PER_SERVING,
    Slot,
)
from larder_core.nutrition import MICROS, Nutrients, micro_totals
from larder_core.quantities import grams_for
from larder_core.tagging import line_tags, make_line, tag_text
from larder_core.units import parse_measure
from larder_db import models as db
from larder_llm.schemas import CreateRecipeInput
from larder_solver import Food, Profile, Recipe
from larder_solver.candidates import allowed

# The recipe's category decides the slots it can fill (larder_core.meals.CATEGORY_SLOTS).
CATEGORY: dict[Slot, str] = {
    Slot.BREAKFAST: "Breakfast",
    Slot.LUNCH: "Miscellaneous",  # lunch or dinner
    Slot.DINNER: "Miscellaneous",
    Slot.SNACK: "Snack",
}


@dataclass(frozen=True, slots=True)
class Created:
    recipe_id: int | None
    problems: list[str]  # empty when saved
    kcal_per_serving: int | None = None
    allergens: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Line:
    name: str
    quantity: str
    match: foods.FoodMatch
    grams: float


async def create_recipe(
    scope: ChatScope,
    draft: CreateRecipeInput,
    *,
    source: str = "generated",
    source_url: str | None = None,
    image_url: str | None = None,
    replacing: int | None = None,
) -> Created:
    """`source` "imported" (with the page's address and photo) for recipes read from the web,
    "custom" for one the user edited; they go through exactly the same checks. `replacing`: an
    edit of the user's own recipe, which then changes in place (same id: favourites, plans and
    links keep pointing at it; plans keep the numbers they were made with)."""
    lines, problems = await _resolve(scope, draft)
    if problems:
        return Created(None, problems)

    async with scope.sessionmaker() as session:
        allergies = await session.get(db.Allergies, scope.user_id)
        preferences = await session.get(db.Preferences, scope.user_id)
        food_rows, info = await planning.load_foods(session, (x.match.food_id for x in lines))
        avoided = (
            await planning.load_foods(session, allergies.avoid_food_ids) if allergies else ({}, {})
        )[0]
    if allergies is None or preferences is None:
        return Created(None, ["Set your allergies and diet in your profile first."])
    profile = planning.profile_of(allergies, preferences)

    missing = [x.name for x in lines if food_rows[x.match.food_id].kcal is None]
    if missing:
        return Created(None, [f"couldn't get nutrition for {_quoted(missing)}"])
    row = _row(scope, draft, lines, food_rows)
    row.source, row.source_url, row.image_url = source, source_url, image_url
    facts = planning.recipe_facts(row, food_rows, info)
    problems = _text_problems(draft, avoided, profile.allergens)
    if draft.slot not in facts.slots:
        problems.append(_slot_problem(draft, row, food_rows))
    recipe = planning.solver_recipe(row, facts, info)
    solver_foods = {fid: planning.solver_food(f, info[fid]) for fid, f in food_rows.items()}
    if recipe is not None and not allowed(recipe, solver_foods, profile):
        problems += _unsafe(lines, info, recipe, solver_foods, profile)
    if problems:
        return Created(None, list(dict.fromkeys(problems)))

    async with scope.sessionmaker() as session:
        if replacing is None:
            session.add(row)
        else:
            target = await session.scalar(
                select(db.Recipe)
                .where(db.Recipe.id == replacing, db.Recipe.owner_user_id == scope.user_id)
                .options(selectinload(db.Recipe.ingredients))
            )
            if target is None:
                return Created(None, ["That recipe can't be changed."])
            _replace(target, row)
            # The old lines go first: (recipe, position) is unique.
            target.ingredients.clear()
            await session.flush()
            target.ingredients.extend(_copy_lines(row))
            row = target
        await session.commit()
    return Created(
        row.id,
        [],
        kcal_per_serving=round(row.kcal or 0),
        allergens=tuple(sorted(facts.tags.allergens)),
    )


async def _resolve(scope: ChatScope, draft: CreateRecipeInput) -> tuple[list[_Line], list[str]]:
    lines: list[_Line] = []
    problems: list[str] = []
    for ingredient in draft.ingredients:
        match = await foods.match_food(scope, ingredient.name)
        if match is None:
            problems.append(f"couldn't match '{ingredient.name}' - use a common ingredient name")
            continue
        food, portions = await foods.food_portions(scope, match.food_id)
        if food is None:
            problems.append(f"couldn't match '{ingredient.name}'")
            continue
        measure = parse_measure(ingredient.quantity)
        staple = planning.food_info(food).staple
        grams = grams_for(measure, portions, ingredient.name.lower(), food.category)
        if measure.vague and not staple:
            problems.append(f"give an amount for '{ingredient.name}' (grams, spoons or a count)")
        elif grams is None and not staple:
            problems.append(
                f"couldn't work out how much '{ingredient.quantity}' of '{ingredient.name}' "
                "is - use grams or a common unit"
            )
        else:
            lines.append(_Line(ingredient.name, ingredient.quantity, match, grams or 0.0))
    return lines, problems


def _row(
    scope: ChatScope,
    draft: CreateRecipeInput,
    lines: list[_Line],
    food_rows: dict[int, db.Food],
) -> db.Recipe:
    def total(field: str) -> float:
        return sum(
            (getattr(food_rows[x.match.food_id], field) or 0.0) * x.grams / 100 for x in lines
        )

    per = {f: total(f) / draft.servings for f in Nutrients.FIELDS}
    per |= micro_totals(
        (({m: getattr(food_rows[x.match.food_id], m) for m in MICROS}, x.grams) for x in lines),
        draft.servings,
    )
    return db.Recipe(
        source="generated",
        source_id=uuid.uuid4().hex,
        name=draft.name.strip(),
        category=CATEGORY[draft.slot],
        cuisine=draft.cuisine,
        instructions=draft.instructions,
        minutes=cook_minutes(draft.instructions),
        servings=draft.servings,
        servings_estimated=False,
        nutrition_complete=True,
        owner_user_id=scope.user_id,
        **per,
        ingredients=[
            db.RecipeIngredient(
                position=i,
                raw_name=x.name,
                raw_measure=x.quantity,
                food_id=x.match.food_id,
                grams=x.grams,
                match_method=x.match.method,
            )
            for i, x in enumerate(lines)
        ],
    )


def _replace(target: db.Recipe, checked: db.Recipe) -> None:
    """An edit's content onto the user's recipe; where it came from (source, link, photo) and
    its id stay."""
    target.name, target.category, target.cuisine = checked.name, checked.category, checked.cuisine
    target.instructions, target.minutes = checked.instructions, checked.minutes
    target.servings, target.servings_estimated = checked.servings, checked.servings_estimated
    target.nutrition_complete = checked.nutrition_complete
    for field in (*Nutrients.FIELDS, *MICROS):
        setattr(target, field, getattr(checked, field))


def _copy_lines(checked: db.Recipe) -> list[db.RecipeIngredient]:
    return [
        db.RecipeIngredient(
            position=i.position,
            raw_name=i.raw_name,
            raw_measure=i.raw_measure,
            food_id=i.food_id,
            grams=i.grams,
            match_method=i.match_method,
        )
        for i in checked.ingredients
    ]


def _quoted(names: list[str]) -> str:
    return ", ".join(f"'{n}'" for n in names)


def _text_problems(
    draft: CreateRecipeInput, avoided: dict[int, db.Food], allergens: frozenset[Allergen]
) -> list[str]:
    """Avoided foods named anywhere in the text, and allergen words in the name or method."""
    words = tokens(f"{draft.name} {draft.instructions}")
    problems: list[str] = []
    for food in avoided.values():
        names = [food.description.split(",")[0]]
        names += [a.name for a in load_alias_rows() if a.fdc_id == food.id]
        if any(_mentions(words, name) for name in names):
            problems.append(
                f"it mentions {food.description.split(',')[0].lower()}, which you avoid"
            )
    text_allergens = tag_text(draft.name).allergens | tag_text(draft.instructions).allergens
    if hit := text_allergens & allergens:
        named = ", ".join(sorted(a.replace("_", " ") for a in hit))
        problems.append(f"the name or method mentions {named}")
    return problems


def _mentions(words: frozenset[str], name: str) -> bool:
    wanted = tokens(name)
    return bool(wanted) and wanted <= words


def _slot_problem(draft: CreateRecipeInput, row: db.Recipe, food_rows: dict[int, db.Food]) -> str:
    kcal = row.kcal or 0
    if kcal > MAX_KCAL_PER_SERVING:
        return (
            f"{kcal:,.0f} kcal per serving is too much for one meal - use more servings or "
            "smaller amounts"
        )
    total_g = sum(i.grams or 0 for i in row.ingredients)
    oil = sum(
        i.grams or 0
        for i in row.ingredients
        if i.food_id is not None and food_rows[i.food_id].category == "Fats and Oils"
    )
    if total_g and oil / total_g > MAX_OIL_SHARE:
        return "too much of it is oil or fat - use less"
    if (row.sodium_mg or 0) > MAX_SODIUM_MG_PER_SERVING:
        return "it has more than a day's salt in a serving - use less salt or more servings"
    return f"it can't be a {draft.slot} recipe"


def _unsafe(
    lines: list[_Line],
    info: dict[int, planning.FoodInfo],
    recipe: Recipe,
    solver_foods: dict[int, Food],
    profile: Profile,
) -> list[str]:
    problems: list[str] = []
    if recipe.unresolved and profile.restricted:
        for x in lines:
            line = make_line(x.name, x.match.food_id, info[x.match.food_id].tags)
            if not line.exact and line_tags(x.name) is None:
                problems.append(
                    f"couldn't verify '{x.name}' against your allergies; use a common "
                    "ingredient name"
                )
    reasons = [
        r for r in planning.unsafe_reasons(recipe, solver_foods, profile) if "couldn't" not in r
    ]
    problems += [f"it {r}" for r in reasons]
    return problems or ["it isn't safe for your allergies or diet"]
