"""search_recipes: recipes safe for this user that match a query, for cravings and swaps.

Pool: the shared plannable catalog (owner IS NULL) plus this user's private recipes (loaded per
request, never cached across users), filtered by the planner's hard
filters (larder_solver.candidates.allowed: allergens incl. text-derived, diet, avoided foods,
unverifiable ingredients for restricted users) and, if given, slot eligibility. No embeddings in
the API (ADR-0013): the model supplies words; we score them against recipe name, category,
cuisine, MealDB tags and ingredient names (whole-word, a small synonym table for qualities like
'spicy' -> chilli, curry, jalapeno, harissa...), then preference and pantry overlap, then id.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_api.chat.foods import tokens
from larder_api.chat.scope import ChatScope
from larder_core.meals import SLOT_ORDER, Slot
from larder_db import models as db
from larder_solver import Profile, Recipe
from larder_solver.candidates import TastePrefs, allowed, preference

# Qualities -> words that show them in a recipe (whole words, singular).
SYNONYMS: dict[str, frozenset[str]] = {
    "spicy": frozenset(
        {
            "chilli",
            "chili",
            "chile",
            "chilly",  # "chillies", singularised
            "chily",
            "curry",
            "jalapeno",
            "harissa",
            "cayenne",
            "sriracha",
            "vindaloo",
            "jerk",
            "gochujang",
            "kimchi",
            "szechuan",
            "sichuan",
            "chipotle",
            "hot",
        }
    ),
    "veggie": frozenset({"vegetarian", "vegan"}),
    "vegetarian": frozenset({"vegetarian", "vegan"}),
    "meaty": frozenset({"beef", "pork", "lamb", "chicken", "goat"}),
    "seafood": frozenset({"seafood", "fish", "salmon", "tuna", "cod", "prawn", "shrimp"}),
    "fishy": frozenset({"seafood", "fish", "salmon", "tuna", "cod"}),
    "cheesy": frozenset({"cheese", "cheddar", "mozzarella", "parmesan", "feta"}),
    "creamy": frozenset({"cream", "creamy", "coconut", "yogurt", "cheese"}),
    "light": frozenset({"salad", "soup", "broth", "starter"}),
    "sweet": frozenset({"dessert", "chocolate", "honey", "cake", "sweet"}),
    "pasta": frozenset({"pasta", "spaghetti", "penne", "lasagne", "lasagna", "macaroni"}),
    "noodle": frozenset({"noodle", "ramen", "udon"}),
    "lasagna": frozenset({"lasagne"}),
    "chili": frozenset({"chilli", "chilly"}),
    "chilli": frozenset({"chili", "chilly"}),
    "curry": frozenset({"curry", "masala", "korma", "tikka", "dal", "dhal"}),
}
# Words that say nothing about the dish.
_STOP = frozenset(
    {
        "something",
        "anything",
        "dish",
        "meal",
        "food",
        "like",
        "want",
        "craving",
        "really",
        "please",
        "kind",
        "sort",
        "style",
        "bit",
        "tonight",
        "today",
        "tomorrow",
        "for",
        "in",
        "on",
        "or",
        "to",
        "i",
        "me",
        "breakfast",
        "lunch",
        "dinner",
        "snack",
        "recipe",
        "good",
        "nice",
    }
)
# How much a matched word counts, by where it matched.
_NAME, _LABEL, _INGREDIENT = 3, 2, 1


@dataclass(frozen=True, slots=True)
class RecipeHit:
    id: int
    name: str
    cuisine: str | None
    slots: tuple[Slot, ...]
    kcal_per_serving: int
    protein_g_per_serving: int
    matched: tuple[str, ...]  # which query words matched, for the model to explain
    uses_pantry: tuple[str, ...]  # pantry foods it uses


@dataclass(frozen=True, slots=True)
class Viewer:
    """The signed-in user as recipe filters see them."""

    profile: Profile
    taste: TastePrefs
    pantry: dict[int, str]  # food id -> name


async def load_viewer(scope: ChatScope) -> Viewer | None:
    """None until the user has set allergies and preferences (nothing is known to be safe)."""
    async with scope.sessionmaker() as session:
        allergies = await session.get(db.Allergies, scope.user_id)
        prefs = await session.get(db.Preferences, scope.user_id)
        pantry = await session.scalars(
            select(db.PantryItem)
            .where(db.PantryItem.user_id == scope.user_id)
            .options(selectinload(db.PantryItem.food))
        )
        stock: dict[int, str] = {}
        for p in pantry:
            stock[p.food_id] = p.food.description
            if p.food.generic_food_id is not None:  # a product counts as its generic
                stock.setdefault(p.food.generic_food_id, p.food.description)
    if allergies is None or prefs is None:
        return None
    return Viewer(planning.profile_of(allergies, prefs), planning.taste_of(prefs), stock)


async def recipe_pool(scope: ChatScope) -> planning.PlanningCatalog:
    """The shared catalogue plus this user's private recipes."""
    shared = await scope.catalog.get(scope.sessionmaker)
    async with scope.sessionmaker() as session:
        private = await planning.load_private_recipes(session, scope.user_id)
    return shared.merged(private)


def query_words(query: str) -> list[str]:
    return sorted(tokens(query) - _STOP)


def _fields(pool: planning.PlanningCatalog, recipe: Recipe) -> list[tuple[int, frozenset[str]]]:
    text = pool.text.get(recipe.id)
    labels = [recipe.cuisine or ""]
    ingredients = [
        pool.catalog.foods[i.food_id].name
        for i in recipe.ingredients
        if i.food_id in pool.catalog.foods
    ]
    if text is not None:
        labels += [text.category or "", *text.tags]
        ingredients += text.ingredients
    return [
        (_NAME, tokens(recipe.name)),
        (_LABEL, tokens(" ".join(labels))),
        (_INGREDIENT, tokens(" ".join(ingredients))),
    ]


def match(
    words: Iterable[str], fields: list[tuple[int, frozenset[str]]]
) -> tuple[int, tuple[str, ...]]:
    """(score, the words that matched): each word counts once, at its best field."""
    total = 0
    matched: list[str] = []
    for word in words:
        forms = SYNONYMS.get(word, frozenset()) | {word}
        best = max((weight for weight, have in fields if forms & have), default=0)
        if best:
            total += best
            matched.append(word)
    return total, tuple(matched)


async def search_recipes(
    scope: ChatScope, query: str, slot: Slot | None, limit: int = 5
) -> list[RecipeHit]:
    words = query_words(query)
    viewer = await load_viewer(scope)
    if not words or viewer is None:
        return []
    pool = await recipe_pool(scope)
    ranked: list[tuple[tuple[int, int, int, int], RecipeHit]] = []
    for recipe in pool.catalog.recipes.values():
        if slot is not None and slot not in recipe.meal_types:
            continue
        if not allowed(recipe, pool.catalog.foods, viewer.profile):
            continue
        points, matched = match(words, _fields(pool, recipe))
        if not points:
            continue
        uses = tuple(
            dict.fromkeys(
                viewer.pantry[i.food_id] for i in recipe.ingredients if i.food_id in viewer.pantry
            )
        )
        hit = RecipeHit(
            id=recipe.id,
            name=recipe.name,
            cuisine=recipe.cuisine,
            slots=tuple(s for s in SLOT_ORDER if s in recipe.meal_types),
            kcal_per_serving=recipe.per_portion.kcal * 2,
            protein_g_per_serving=recipe.per_portion.protein_g * 2,
            matched=matched,
            uses_pantry=uses,
        )
        key = (-points, -preference(recipe, viewer.taste), -len(uses), recipe.id)
        ranked.append((key, hit))
    ranked.sort(key=lambda pair: pair[0])
    return [hit for _, hit in ranked[: max(limit, 0)]]


# --- one recipe the model names (handlers.visible_recipe / guard_recipe; also the executor) ----

CANT_USE = "I can't use that recipe."


async def visible_recipe(scope: ChatScope, recipe_id: int) -> db.Recipe | None:
    """The recipe if it is in the shared catalogue or owned by this user, else None."""
    async with scope.sessionmaker() as session:
        return await session.scalar(
            select(db.Recipe)
            .where(
                db.Recipe.id == recipe_id,
                or_(db.Recipe.owner_user_id.is_(None), db.Recipe.owner_user_id == scope.user_id),
            )
            .options(selectinload(db.Recipe.ingredients))
        )


async def guard_recipe(scope: ChatScope, recipe_id: int, slot: Slot) -> str | None:
    """None if the recipe may be chosen for `slot` for this user: visible, plannable, `slot`
    among its meal types and `candidates.allowed` under the current profile; else why not.
    Another user's recipe gets the same answer as a missing one."""
    recipe = await visible_recipe(scope, recipe_id)
    if recipe is None:
        return CANT_USE
    async with scope.sessionmaker() as session:
        allergies = await session.get(db.Allergies, scope.user_id)
        preferences = await session.get(db.Preferences, scope.user_id)
        foods, info = await planning.load_foods(
            session, (i.food_id for i in recipe.ingredients if i.food_id is not None)
        )
    if allergies is None or preferences is None:
        return "Tell me about your allergies and diet in your profile first."
    if not recipe.nutrition_complete or recipe.servings is None:
        return f"{recipe.name} can't be planned: we don't have its full nutrition."
    facts = planning.recipe_facts(recipe, foods, info)
    if slot not in facts.slots:
        return f"{recipe.name} isn't a {slot} recipe."
    planned = planning.solver_recipe(recipe, facts, info)
    if planned is None:
        return f"{recipe.name} can't be planned."
    profile = planning.profile_of(allergies, preferences)
    solver_foods = {fid: planning.solver_food(f, info[fid]) for fid, f in foods.items()}
    if not allowed(planned, solver_foods, profile):
        why = "; it ".join(planning.unsafe_reasons(planned, solver_foods, profile))
        return f"{recipe.name} isn't safe for you: it {why or 'breaks your restrictions'}."
    return None
