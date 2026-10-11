"""A few real chat conversations against Claude (`make llm-smoke`). Not run in CI: it needs
ANTHROPIC_API_KEY and a seeded DATABASE_URL (`make seed`), and costs a few cents.

It makes a throwaway user (peanut allergy, ordinary goals) with a plan starting today, then sends
four messages - a craving, food eaten off-plan, a skip, a swap - through the same path as
POST /chat/messages (the gate, then service.run_turn), printing every event and each turn's cost
and cache use from llm_calls. Then it checks, from stored rows only, that nothing planned or
created for the user conflicts with their allergies, diet or avoided foods (what the tests'
assert_user_safe checks), and deletes the user whatever happened.

    uv run larder-llm-smoke [--keep]
"""

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, date, datetime, timedelta

import anyio
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from larder_api import planning
from larder_api.chat import gate, service
from larder_api.chat.gate import ChatRefused
from larder_api.chat.models import get_models
from larder_api.routers.plans import get_planner, get_replan_planner
from larder_api.schemas import ChatMessageIn, DoneEvent
from larder_api.settings import Settings, get_settings
from larder_core.allergens import Allergen
from larder_core.tagging import Diet, diet_allows
from larder_db import models as db
from larder_db.engine import make_engine, make_sessionmaker

ALLERGENS = ["peanuts"]
TURNS = (
    "I'm craving something spicy for dinner tonight",
    "I had two slices of pepperoni pizza for lunch",
    "I'll skip breakfast tomorrow, not hungry",
    "Can you swap Friday's dinner for something different?",
)


async def make_user(maker: async_sessionmaker[AsyncSession]) -> int:
    async with maker() as session, session.begin():
        user = db.User(auth_subject=f"llm-smoke-{uuid.uuid4()}")
        session.add(user)
        await session.flush()
        session.add_all(
            [
                db.Goals(
                    user_id=user.id,
                    goal="maintain",
                    kcal_min=1800,
                    kcal_max=2400,
                    calorie_floor=1400,
                    max_daily_deficit=500,
                    protein_g_min=80,
                    currency="GBP",
                ),
                db.Allergies(user_id=user.id, allergens=ALLERGENS, avoid_food_ids=[]),
                db.Preferences(
                    user_id=user.id,
                    diet=None,
                    liked_cuisines=[],
                    disliked_cuisines=[],
                    liked_food_ids=[],
                    disliked_food_ids=[],
                ),
            ]
        )
        return user.id


async def make_plan(
    maker: async_sessionmaker[AsyncSession], user_id: int, start: date, settings: Settings
) -> int:
    """A first plan from `start`, the way POST /plans makes one."""
    async with maker() as session:
        user = await session.get(db.User, user_id)
        assert user is not None
        inputs = await planning.load_inputs(session, user)
        catalog = await planning.load_catalog(session)
        private = await planning.load_private_recipes(session, user_id)
        seed = planning.plan_seed(user_id, start, 1)
        problem = planning.make_problem(
            inputs, catalog, start, k=settings.plan_candidates, seed=seed, private=private
        )
        result = await anyio.to_thread.run_sync(get_planner(settings), problem, None)
        plan, violations = planning.check_outcome(problem, result)
        stats = planning.plan_stats(
            problem, result, plan, violations, seed=seed, time_limit_ms=settings.plan_time_limit_ms
        )
        row = planning.save_plan(
            session,
            user_id,
            planning.Prepared(problem, 1, seed, None),
            result,
            plan,
            stats,
            inputs.goals.currency,
            catalog.unshoppable | private.unshoppable,
        )
        await session.commit()
        return row.id


async def show(event: object) -> None:
    """One SSE event, as the client would get it (text deltas inline)."""
    assert isinstance(event, BaseModel)
    dumped = event.model_dump(mode="json")
    kind = dumped.pop("type")
    if kind == "text":
        print(dumped["delta"], end="", flush=True)
    elif kind == "done":
        message = dumped["message"]
        print(f"\n  [done] mode={message['mode']} offline_reason={message['offline_reason']}")
    elif kind in ("outcome", "recipe"):
        print(f"\n  [{kind}] {dumped}")
    else:
        print(f"\n  [{kind}] {dumped}", flush=True)


async def spend(maker: async_sessionmaker[AsyncSession], user_id: int) -> tuple[int, int, int, int]:
    """(requests, cost in micro-dollars, cache-read tokens, cache-write tokens) so far."""
    async with maker() as session:
        row = (
            await session.execute(
                select(
                    func.count(db.LlmCall.id),
                    func.coalesce(func.sum(db.LlmCall.cost_micro_usd), 0),
                    func.coalesce(func.sum(db.LlmCall.cache_read_tokens), 0),
                    func.coalesce(func.sum(db.LlmCall.cache_write_tokens), 0),
                ).where(db.LlmCall.user_id == user_id)
            )
        ).one()
        return int(row[0]), int(row[1]), int(row[2]), int(row[3])


async def turn(
    maker: async_sessionmaker[AsyncSession],
    user_id: int,
    text: str,
    today: date,
    settings: Settings,
    cache: planning.CatalogCache,
) -> bool:
    """One message through the gate and the turn; True when it ended with `done`."""
    print(f"\n> {text}")
    now = datetime.now(UTC)
    body = ChatMessageIn(
        text=text, client_id=uuid.uuid4(), today=today, local_time=datetime.now().time()
    )
    try:
        async with maker() as session:
            prepared = await gate.prepare(
                session, user_id, body, get_models(settings), settings, now
            )
    except ChatRefused as refused:
        print(f"  refused: {refused.status_code} {refused.problem.model_dump(mode='json')}")
        return False
    scope = service.make_scope(
        prepared,
        emit=show,
        sessionmaker=maker,
        catalog=cache,
        planner=get_replan_planner(settings),
        settings=settings,
        now=now,
    )
    done = False
    with anyio.fail_after(settings.chat_turn_deadline_s):
        async for event in service.run_turn(prepared, scope):
            await show(event)
            done = isinstance(event, DoneEvent)
    return done


async def unsafe(maker: async_sessionmaker[AsyncSession], user_id: int, today: date) -> list[str]:
    """Meals of the latest plan from today, and recipes the user owns, that conflict with the
    user's allergies, diet or avoided foods - recomputed from stored rows by the tagger."""
    async with maker() as session:
        allergies = await session.get(db.Allergies, user_id)
        prefs = await session.get(db.Preferences, user_id)
        assert allergies is not None
        assert prefs is not None
        allergens = frozenset(Allergen(a) for a in allergies.allergens)
        avoid = frozenset(allergies.avoid_food_ids)
        diet = Diet(prefs.diet) if prefs.diet else None
        plan = await planning.latest_plan(session, user_id)
        checked: list[tuple[str, int]] = []
        if plan is not None:
            for meal in plan.meals:
                on = plan.start_date + timedelta(days=meal.day)
                if on >= today:
                    checked.append((f"{on} {meal.slot}", meal.recipe_id))
        owned = await session.scalars(
            select(db.Recipe.id).where(db.Recipe.owner_user_id == user_id)
        )
        checked += [(f"own recipe {rid}", rid) for rid in owned]
        recipes = {
            r.id: r
            for r in await session.scalars(
                select(db.Recipe)
                .where(db.Recipe.id.in_({rid for _, rid in checked}))
                .options(selectinload(db.Recipe.ingredients))
            )
        }
        foods, info = await planning.load_foods(
            session,
            (i.food_id for r in recipes.values() for i in r.ingredients if i.food_id is not None),
        )
    problems: list[str] = []
    for where, rid in checked:
        recipe = recipes[rid]
        tags = planning.recipe_facts(recipe, foods, info).tags
        used = {i.food_id for i in recipe.ingredients if i.food_id is not None}
        if hit := tags.allergens & allergens:
            problems.append(f"{where}: {recipe.name} contains {sorted(hit)}")
        if not diet_allows(diet, tags.animal):
            problems.append(f"{where}: {recipe.name} isn't {diet}")
        if hit_foods := used & avoid:
            problems.append(f"{where}: {recipe.name} uses avoided foods {sorted(hit_foods)}")
        if (allergens or avoid or diet) and tags.unresolved:
            problems.append(f"{where}: {recipe.name} has unverified ingredients")
    return problems


async def run(keep: bool) -> int:
    settings = get_settings()
    if not settings.llm_enabled:
        print("Set ANTHROPIC_API_KEY (and llm_mode=auto): this smoke test talks to Claude.")
        return 2
    engine = make_engine(settings.database_url)
    maker = make_sessionmaker(engine)
    today = datetime.now().date()
    user_id = await make_user(maker)
    failures: list[str] = []
    try:
        plan_id = await make_plan(maker, user_id, today, settings)
        print(f"user {user_id}, plan {plan_id} from {today} (allergic to {', '.join(ALLERGENS)})")
        cache = planning.CatalogCache()
        before = await spend(maker, user_id)
        for text in TURNS:
            if not await turn(maker, user_id, text, today, settings, cache):
                failures.append(f"no reply to {text!r}")
            after = await spend(maker, user_id)
            delta = [a - b for a, b in zip(after, before, strict=True)]
            requests, cost, cache_read, cache_write = delta
            print(
                f"  {requests} requests, ${cost / 1e6:.4f}, cache read {cache_read} / "
                f"written {cache_write} tokens"
            )
            before = after
        total = (await spend(maker, user_id))[1]
        print(f"\ntotal ${total / 1e6:.4f} for {len(TURNS)} turns")
        failures += await unsafe(maker, user_id, today)
    finally:
        if keep:
            print(f"kept user {user_id}")
        else:
            async with maker() as session, session.begin():
                await session.execute(delete(db.User).where(db.User.id == user_id))
        await engine.dispose()
    for failure in failures:
        print(f"FAIL: {failure}")
    print("OK" if not failures else f"{len(failures)} problem(s)")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Real chat turns against Claude.")
    parser.add_argument("--keep", action="store_true", help="don't delete the throwaway user")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(keep=args.keep)))


if __name__ == "__main__":
    main()
