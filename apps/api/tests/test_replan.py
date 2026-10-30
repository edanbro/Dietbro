"""The replan executor (larder_api.changes.replan.apply_changes) against the database, with fixed
dates: the plan runs Monday 12 to Sunday 18 Oct 2026 and it is Wednesday 14 Oct, 12:00 (so
today's breakfast is over). The planner is the greedy baseline, or `strict`: the same plans with
CP-SAT semantics (any hard miss - a kcal band included - means no plan)."""

import uuid
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from typing import Any, Literal

import anyio
import httpx
import pytest
from safety import assert_user_safe
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from larder_api import eaten, planning
from larder_api.changes.replan import apply_changes
from larder_api.changes.scope import ChangeScope, Models
from larder_api.settings import Settings
from larder_core.meals import Slot
from larder_db import models as db
from larder_db.engine import make_sessionmaker
from larder_llm.outcome import ReplanOutcome
from larder_llm.schemas import AteOffPlan, Change, Craving, OffPlanItem, Skip, Swap, When
from larder_solver import (
    Band,
    Macros,
    Nutrient,
    Plan,
    PlanResult,
    Problem,
    Recipe,
    SlotSpec,
    Status,
    Targets,
    greedy,
    hard,
    validate,
)

MON = date(2026, 10, 12)
TUE, TODAY, THU, FRI, SAT, SUN = (MON + timedelta(days=d) for d in range(1, 7))
NEXT_MON = MON + timedelta(days=7)
NOON = time(12, 0)
B, L, D, S = Slot.BREAKFAST, Slot.LUNCH, Slot.DINNER, Slot.SNACK

GREEDY: planning.Planner = partial(
    planning.run_planner, mode="greedy", time_limit_ms=2000, workers=1
)


def strict(problem: Problem, previous: Plan | None) -> PlanResult:
    """CP-SAT semantics: every hard rule (kcal bands included) holds, or there is no plan."""
    result = greedy(problem, previous)
    if result.plan is not None and hard(validate(problem, result.plan)):
        return replace(result, status=Status.INFEASIBLE, plan=None, planner="cpsat")
    return replace(result, planner="cpsat")


PLANNERS = pytest.mark.parametrize("planner", [GREEDY, strict], ids=["greedy", "strict"])


# --- changes ----------------------------------------------------------------------------------


def craving(
    on: date,
    slot: Slot | None,
    dish: str | None = None,
    *,
    recipe_id: int | None = None,
    tags: Sequence[str] = (),
    strength: Literal["hard", "soft"] = "hard",
) -> Craving:
    return Craving(
        intent="craving",
        when=When(date=on, slot=slot),
        dish=dish,
        tags=list(tags),
        recipe_id=recipe_id,
        strength=strength,
    )


def ate(
    on: date, slot: Slot | None, description: str, *items: tuple[str, str | None]
) -> AteOffPlan:
    return AteOffPlan(
        intent="ate_off_plan",
        when=When(date=on, slot=slot),
        description=description,
        items=[OffPlanItem(name=n, quantity=q) for n, q in items],
    )


def skip(on: date, slot: Slot | None, *, elsewhere: bool) -> Skip:
    return Skip(intent="skip", when=When(date=on, slot=slot), eating_elsewhere=elsewhere)


def swap(on: date, slot: Slot, dish: str | None = None, *, recipe_id: int | None = None) -> Swap:
    return Swap(intent="swap", when=When(date=on, slot=slot), dish=dish, recipe_id=recipe_id)


PIZZA_SLICES = ate(TODAY, L, "2 slices of pizza", ("pizza", "2 slices"))
PIZZA_SLICES_KCAL = round(268 * 2 * 63 / 100)


# --- the world: a user and a plan ------------------------------------------------------------


@dataclass
class World:
    maker: async_sessionmaker[AsyncSession]
    user_id: int
    recipes: dict[str, int]
    v1: int  # the first plan's id
    planner: planning.Planner = GREEDY
    cache: planning.CatalogCache = field(default_factory=planning.CatalogCache)
    runs: list[int] = field(default_factory=list[int])  # planner runs per apply_changes

    def scope(
        self,
        client_id: uuid.UUID,
        *,
        today: date = TODAY,
        local_time: time | None = NOON,
        planner: planning.Planner | None = None,
        models: Models | None = None,
        calls: list[int] | None = None,
    ) -> ChangeScope:
        base = planner or self.planner

        def counted(problem: Problem, previous: Plan | None) -> PlanResult:
            if calls is not None:
                calls.append(1)
            return base(problem, previous)

        async def nothing(_: object) -> None:
            return None

        return ChangeScope(
            user_id=self.user_id,
            today=today,
            local_time=local_time,
            now=datetime.combine(today, local_time or time(12), UTC),
            sessionmaker=self.maker,
            catalog=self.cache,
            planner=counted,
            settings=Settings(),
            models=models or Models(),
            log_call=nothing,
            client_id=client_id,
        )

    async def say(
        self,
        *changes: Change,
        today: date = TODAY,
        local_time: time | None = NOON,
        planner: planning.Planner | None = None,
        request: uuid.UUID | None = None,
    ) -> ReplanOutcome:
        calls: list[int] = []
        scope = self.scope(
            request or uuid.uuid4(),
            today=today,
            local_time=local_time,
            planner=planner,
            calls=calls,
        )
        out = await apply_changes(scope, list(changes))
        self.runs.append(len(calls))
        assert len(calls) <= 3
        async with self.maker() as session:
            await assert_user_safe(session, self.user_id, today)
        return out

    async def plan(self, plan_id: int | None = None) -> db.MealPlan:
        """A plan version (default: the latest) with its meals and shopping list."""
        async with self.maker() as session:
            query = select(db.MealPlan).options(
                selectinload(db.MealPlan.meals), selectinload(db.MealPlan.shopping)
            )
            if plan_id is None:
                query = query.where(db.MealPlan.user_id == self.user_id).order_by(
                    db.MealPlan.created_at.desc(), db.MealPlan.id.desc()
                )
            else:
                query = query.where(db.MealPlan.id == plan_id)
            row = await session.scalar(query.limit(1))
            assert row is not None
            return row

    async def versions(self) -> int:
        async with self.maker() as session:
            n = await session.scalar(
                select(func.count(db.MealPlan.id)).where(db.MealPlan.user_id == self.user_id)
            )
            return n or 0

    async def logs(self) -> list[db.MealLog]:
        async with self.maker() as session:
            rows = await session.scalars(
                select(db.MealLog).where(db.MealLog.user_id == self.user_id).order_by(db.MealLog.id)
            )
            return list(rows)

    async def cravings(self) -> list[db.Craving]:
        async with self.maker() as session:
            rows = await session.scalars(
                select(db.Craving).where(db.Craving.user_id == self.user_id).order_by(db.Craving.id)
            )
            return list(rows)

    def name(self, recipe_id: int | None) -> str | None:
        return next((n for n, i in self.recipes.items() if i == recipe_id), None)


type MakeWorld = Callable[..., Awaitable[World]]


@pytest.fixture
def make_world(
    db_engine: AsyncEngine,
    menu: dict[str, int],
    new_user: Callable[..., Awaitable[int]],
    make_plan: Callable[[int, date], Coroutine[Any, Any, int]],
) -> MakeWorld:
    async def make(*, start: date = MON, sub: str = "user_a", **profile: Any) -> World:
        user_id = await new_user(sub, **profile)
        plan_id = await make_plan(user_id, start)
        return World(make_sessionmaker(db_engine), user_id, menu, plan_id)

    return make


@pytest.fixture
async def world(make_world: MakeWorld) -> World:
    return await make_world()


def meal(plan: db.MealPlan, on: date, slot: Slot) -> db.PlanMeal | None:
    day = (on - plan.start_date).days
    return next((m for m in plan.meals if m.day == day and m.slot == slot), None)


def day_meals(plan: db.MealPlan, on: date) -> dict[str, tuple[int, int]]:
    day = (on - plan.start_date).days
    return {m.slot: (m.recipe_id, m.portions) for m in plan.meals if m.day == day}


def stats(plan: db.MealPlan) -> planning.PlanStats:
    return planning.PlanStats.model_validate(plan.stats)


def total(plan: db.MealPlan, on: date) -> int:
    return stats(plan).day_totals[(on - plan.start_date).days].kcal


def meals_kcal(plan: db.MealPlan, on: date) -> int:
    day = (on - plan.start_date).days
    return sum(m.kcal for m in plan.meals if m.day == day)


def logged(plan: db.MealPlan, on: date) -> list[str]:
    return [entry.description for entry in stats(plan).logged_on((on - plan.start_date).days)]


def past_rows(plan: db.MealPlan) -> list[tuple[int, str, int, int, int]]:
    return sorted((m.day, m.slot, m.recipe_id, m.portions, m.kcal) for m in plan.meals if m.day < 2)


# --- wishes -----------------------------------------------------------------------------------


@PLANNERS
async def test_hard_craving_pins_the_matching_recipe(
    world: World, planner: planning.Planner
) -> None:
    v1 = await world.plan()

    out = await world.say(craving(THU, D, "lasagne"), planner=planner)

    assert [r.status for r in out.results] == ["applied"]
    assert out.results[0].recipe_name == "Lasagne"
    v2 = await world.plan()
    assert (out.plan_id, out.version, v2.version, v2.parent_id) == (v2.id, 2, 2, v1.id)
    thu = meal(v2, THU, D)
    assert thu is not None
    assert thu.recipe_id == world.recipes["Lasagne"]
    assert thu.locked
    assert past_rows(v2) == past_rows(v1)
    before = meal(v1, THU, D)
    assert before is not None
    if before.recipe_id != thu.recipe_id:
        change = next(c for c in out.changes if (c.date, c.slot) == (THU, D))
        assert (change.reason, change.change_index, change.after) == ("craving", 0, "Lasagne")
    [row] = await world.cravings()
    assert (row.intent, row.status, row.plan_id) == ("craving", "applied", v2.id)
    assert world.runs == [1]
    assert stats(v2).outcome is not None


async def test_soft_craving_by_tags_applies_when_it_fits(world: World) -> None:
    out = await world.say(craving(FRI, D, tags=["spicy"], strength="soft"))

    assert out.results[0].status == "applied"
    fri = meal(await world.plan(), FRI, D)
    assert fri is not None
    assert world.name(fri.recipe_id) in {"Chicken curry", "Chilli con carne"}
    assert fri.locked


async def test_craving_with_no_safe_match_fails_and_keeps_the_plan(make_world: MakeWorld) -> None:
    world = await make_world(allergens=["peanuts"])

    out = await world.say(craving(FRI, D, "satay"))

    assert out.results[0].status == "failed"
    assert "satay" in out.results[0].message.lower()
    assert out.plan_id is None
    assert await world.versions() == 1
    [row] = await world.cravings()
    assert (row.status, row.plan_id) == ("failed", world.v1)
    assert world.runs == [0]


async def test_soft_craving_that_cannot_fit_fails_with_the_reason(make_world: MakeWorld) -> None:
    # A 1,700 kcal day can't hold a 1,000 kcal dinner (a serving at least) plus the lightest
    # breakfast and lunch: CP-SAT semantics find no plan, so the wish is dropped.
    world = await make_world(kcal=(1500, 1700), protein=None)

    out = await world.say(craving(THU, D, "feast", strength="soft"), planner=strict)

    assert out.results[0].status == "failed"
    assert out.plan_id is None
    assert await world.versions() == 1
    assert world.runs == [1]


async def test_craving_for_a_recipe_id(world: World) -> None:
    risotto = world.recipes["Mushroom risotto"]

    out = await world.say(craving(FRI, L, recipe_id=risotto))

    assert out.results[0].status == "applied"
    fri = meal(await world.plan(), FRI, L)
    assert fri is not None
    assert (fri.recipe_id, fri.locked) == (risotto, True)


@pytest.mark.parametrize(
    ("which", "slot", "expected"),
    [
        ("other_users", D, "I can't use that recipe"),
        ("missing", D, "I can't use that recipe"),
        ("unplannable", D, "can't be planned"),
        ("Porridge", D, "isn't a dinner recipe"),
        ("Satay rice", D, "isn't safe for you"),
    ],
)
async def test_craving_for_a_recipe_id_that_cannot_be_used_fails(
    make_world: MakeWorld,
    new_user: Callable[..., Awaitable[int]],
    add_recipe: Callable[..., Awaitable[int]],
    which: str,
    slot: Slot,
    expected: str,
) -> None:
    world = await make_world(allergens=["peanuts"])
    stew = [("lentil", 172420, 240), ("tomato", 170457, 600)]
    if which == "other_users":
        other = await new_user("user_b")
        recipe_id = await add_recipe("Secret stew", "Vegetarian", 500, 30, stew, owner=other)
    elif which == "missing":
        recipe_id = 999_999
    elif which == "unplannable":
        recipe_id = await add_recipe("Half-known stew", "Vegetarian", 500, 30, stew, complete=False)
    else:
        recipe_id = world.recipes[which]

    out = await world.say(craving(FRI, slot, recipe_id=recipe_id))

    assert out.results[0].status == "failed"
    assert expected in out.results[0].message
    assert out.plan_id is None
    assert await world.versions() == 1


async def test_swap_to_a_named_dish(world: World) -> None:
    out = await world.say(swap(THU, L, "risotto"))

    assert out.results[0].status == "applied"
    thu = meal(await world.plan(), THU, L)
    assert thu is not None
    assert thu.recipe_id == world.recipes["Mushroom risotto"]
    assert thu.locked


@PLANNERS
async def test_swap_without_a_target_picks_something_else(
    world: World, planner: planning.Planner
) -> None:
    v1 = await world.plan()
    before = meal(v1, THU, D)
    assert before is not None
    elsewhere_that_day = {r for slot, (r, _) in day_meals(v1, THU).items() if slot != D}

    out = await world.say(swap(THU, D), planner=planner)

    assert out.results[0].status == "applied"
    after = meal(await world.plan(), THU, D)
    assert after is not None
    assert after.locked
    assert after.recipe_id != before.recipe_id
    assert after.recipe_id not in elsewhere_that_day
    change = next(c for c in out.changes if (c.date, c.slot) == (THU, D))
    assert (change.reason, change.change_index) == ("swap", 0)


async def test_wishes_on_past_days_fail(world: World) -> None:
    out = await world.say(swap(TUE, D), craving(MON, L, "lasagne"))

    assert [r.status for r in out.results] == ["failed", "failed"]
    assert all("past days" in r.message.lower() for r in out.results)
    assert out.plan_id is None
    assert await world.versions() == 1


async def test_a_wish_on_a_meal_already_over_today_fails(world: World) -> None:
    out = await world.say(craving(TODAY, B, "porridge"))

    assert out.results[0].status == "failed"
    assert out.plan_id is None


# --- facts ------------------------------------------------------------------------------------


async def test_skip_eating_elsewhere_counts_the_planned_meal(world: World) -> None:
    v1 = await world.plan()
    planned = meal(v1, FRI, D)
    assert planned is not None

    out = await world.say(skip(FRI, D, elsewhere=True))

    assert out.results[0].status == "applied"
    v2 = await world.plan()
    assert meal(v2, FRI, D) is None
    [log] = await world.logs()
    assert (log.kind, log.slot, log.eaten_on, log.kcal) == ("skipped", "dinner", FRI, planned.kcal)
    assert (log.plan_id, log.voided_at, log.source) == (v2.id, None, "app")
    assert total(v2, FRI) == meals_kcal(v2, FRI) + planned.kcal
    assert len(logged(v2, FRI)) == 1
    assert [(e.kind, e.kcal) for e in out.logged] == [("skipped", planned.kcal)]


@PLANNERS
async def test_skip_without_eating_saves_a_lighter_day(
    world: World, planner: planning.Planner
) -> None:
    out = await world.say(skip(TODAY, D, elsewhere=False), planner=planner)

    assert out.results[0].status == "applied"
    v2 = await world.plan()
    assert v2.version == 2
    assert meal(v2, TODAY, D) is None
    [log] = await world.logs()
    assert (log.kind, log.kcal, log.estimated) == ("skipped", 0, False)
    assert not [v for v in stats(v2).violations if v.code == "calorie_floor"]
    today = next(d for d in out.days if d.date == TODAY)
    assert today.relaxed


async def test_off_plan_food_is_estimated_from_usda_data(world: World) -> None:
    out = await world.say(PIZZA_SLICES)

    assert out.results[0].status == "applied"
    [log] = await world.logs()
    assert (log.kind, log.slot, log.kcal, log.estimated) == (
        "off_plan",
        "lunch",
        PIZZA_SLICES_KCAL,
        False,
    )
    assert log.items == [
        {"name": "pizza", "food_id": 1_900_001, "food": log.items[0]["food"], "grams": 126}
    ]
    v2 = await world.plan()
    assert meal(v2, TODAY, L) is None
    assert total(v2, TODAY) == meals_kcal(v2, TODAY) + PIZZA_SLICES_KCAL
    assert logged(v2, TODAY) == ["2 slices of pizza"]


async def test_unmatched_off_plan_food_counts_as_the_planned_meal(world: World) -> None:
    planned = meal(await world.plan(), TODAY, L)
    assert planned is not None

    out = await world.say(ate(TODAY, L, "a zorblax stew"))

    assert out.results[0].status == "applied"
    [log] = await world.logs()
    assert (log.kcal, log.estimated) == (planned.kcal, True)
    assert "tell me what was in it" in out.results[0].message


async def test_off_plan_food_on_a_past_day_is_logged_on_that_day(world: World) -> None:
    v1 = await world.plan()

    out = await world.say(ate(TUE, D, "2 slices of pizza", ("pizza", "2 slices")))

    assert out.results[0].status == "applied"
    v2 = await world.plan()
    assert v2.version == 2
    assert meal(v2, TUE, D) is None
    assert logged(v2, TUE) == ["2 slices of pizza"]
    assert total(v2, TUE) == meals_kcal(v2, TUE) + PIZZA_SLICES_KCAL
    # Nothing else moves; no planner run is needed.
    assert world.runs == [0]
    rows = {(m.day, m.slot, m.recipe_id, m.portions) for m in v1.meals}
    kept = {row for row in rows if row[:2] != (1, "dinner")}
    assert {(m.day, m.slot, m.recipe_id, m.portions) for m in v2.meals} == kept


async def test_off_plan_food_outside_the_plan_is_only_logged(world: World) -> None:
    out = await world.say(ate(NEXT_MON, L, "a sandwich"))

    assert out.results[0].status == "applied"
    assert out.plan_id is None
    assert await world.versions() == 1
    [log] = await world.logs()
    assert (log.eaten_on, log.plan_id) == (NEXT_MON, None)


async def test_off_plan_without_a_meal_today_takes_the_latest_meal_begun(world: World) -> None:
    out = await world.say(ate(TODAY, None, "a pizza"), local_time=time(13, 0))

    assert out.results[0].slot == L
    assert "lunch" in out.results[0].message


@PLANNERS
async def test_a_huge_off_plan_lunch_still_saves_a_version(
    world: World, planner: planning.Planner
) -> None:
    out = await world.say(ate(TODAY, L, "a whole pizza", ("pizza", "750 g")), planner=planner)

    assert out.results[0].status == "applied"
    v2 = await world.plan()
    assert v2.version == 2
    today = next(d for d in out.days if d.date == TODAY)
    assert today.kcal > 2300
    assert not today.within
    assert today.relaxed
    assert total(v2, TODAY) == today.kcal


# --- several changes and several messages -----------------------------------------------------


async def test_facts_and_wishes_in_one_message_make_one_version(world: World) -> None:
    out = await world.say(PIZZA_SLICES, craving(FRI, D, "lasagne"), skip(SAT, L, elsewhere=True))

    assert [r.status for r in out.results] == ["applied"] * 3
    assert await world.versions() == 2
    assert world.runs == [1]
    v2 = await world.plan()
    fri = meal(v2, FRI, D)
    assert fri is not None
    assert fri.recipe_id == world.recipes["Lasagne"]
    assert meal(v2, TODAY, L) is None
    assert meal(v2, SAT, L) is None
    assert {log.kind for log in await world.logs()} == {"off_plan", "skipped"}


async def test_off_plan_beats_a_skip_of_the_same_meal(world: World) -> None:
    out = await world.say(skip(FRI, D, elsewhere=True), ate(FRI, D, "a burger"))

    assert [r.status for r in out.results] == ["unchanged", "applied"]
    assert [log.kind for log in await world.logs()] == ["off_plan"]


async def test_a_wish_on_a_meal_reported_in_the_same_message_fails(world: World) -> None:
    out = await world.say(skip(FRI, L, elsewhere=False), craving(FRI, L, "lasagne"))

    assert [r.status for r in out.results] == ["applied", "failed"]
    assert "skipping" in out.results[1].message


async def test_of_two_wishes_for_one_meal_the_first_wins(world: World) -> None:
    out = await world.say(craving(SAT, D, "lasagne"), craving(SAT, D, "curry"))

    assert [r.status for r in out.results] == ["applied", "failed"]
    sat = meal(await world.plan(), SAT, D)
    assert sat is not None
    assert sat.recipe_id == world.recipes["Lasagne"]


@PLANNERS
async def test_later_messages_keep_earlier_logs(world: World, planner: planning.Planner) -> None:
    await world.say(PIZZA_SLICES, planner=planner)

    out = await world.say(swap(THU, D), planner=planner)

    assert out.results[0].status == "applied"
    v3 = await world.plan()
    assert v3.version == 3
    assert meal(v3, TODAY, L) is None
    assert logged(v3, TODAY) == ["2 slices of pizza"]
    assert total(v3, TODAY) == meals_kcal(v3, TODAY) + PIZZA_SLICES_KCAL


async def test_a_craving_after_a_skip_of_that_meal_voids_the_skip(world: World) -> None:
    await world.say(skip(FRI, D, elsewhere=False))

    out = await world.say(craving(FRI, D, "lasagne"))

    assert out.results[0].status == "applied"
    v3 = await world.plan()
    fri = meal(v3, FRI, D)
    assert fri is not None
    assert fri.recipe_id == world.recipes["Lasagne"]
    [log] = await world.logs()
    assert log.voided_at is not None
    assert logged(v3, FRI) == []


async def test_a_wish_on_a_meal_logged_off_plan_fails(world: World) -> None:
    await world.say(ate(FRI, L, "a burger"))

    out = await world.say(craving(FRI, L, "lasagne"))

    assert out.results[0].status == "failed"
    assert "already logged" in out.results[0].message
    assert await world.versions() == 2


@pytest.mark.parametrize("replans", [False, True], ids=["copied", "replanned"])
async def test_a_logged_meal_is_never_also_carried_over(world: World, replans: bool) -> None:
    # Logged while no version could be saved (goals under review) or before POST /plans made
    # the plan again: the parent still has the planned meal for those cells.
    async with world.maker() as session:
        for on, slot in ((TUE, D), (TODAY, B)):
            session.add(
                db.MealLog(
                    user_id=world.user_id,
                    eaten_on=on,
                    slot=slot.value,
                    kind="off_plan",
                    description="a sandwich",
                    kcal=500,
                    protein_g=20,
                    fat_g=20,
                    carbs_g=60,
                    source="app",
                    plan_id=world.v1,
                )
            )
        await session.commit()
    later = (skip(FRI, D, elsewhere=False),) if replans else ()

    await world.say(ate(TUE, L, "2 slices of pizza", ("pizza", "2 slices")), *later)

    v2 = await world.plan()
    assert meal(v2, TUE, D) is None
    assert meal(v2, TODAY, B) is None
    assert total(v2, TUE) == meals_kcal(v2, TUE) + 500 + PIZZA_SLICES_KCAL
    assert total(v2, TODAY) == meals_kcal(v2, TODAY) + 500


async def test_a_new_log_for_a_meal_replaces_the_earlier_one(world: World) -> None:
    await world.say(ate(TODAY, L, "a whole pizza", ("pizza", "750 g")))

    await world.say(ate(TODAY, L, "actually just 2 slices of pizza", ("pizza", "2 slices")))

    first, second = await world.logs()
    assert first.voided_at is not None
    assert second.voided_at is None
    v3 = await world.plan()
    assert total(v3, TODAY) == meals_kcal(v3, TODAY) + PIZZA_SLICES_KCAL


@PLANNERS
async def test_an_allergy_added_mid_week_never_blocks_a_replan(
    world: World, planner: planning.Planner
) -> None:
    # Monday's dinner had peanuts; on Wednesday the user adds a peanut allergy.
    satay = world.recipes["Satay rice"]
    async with world.maker() as session:
        await session.execute(
            update(db.PlanMeal)
            .where(
                db.PlanMeal.plan_id == world.v1, db.PlanMeal.day == 0, db.PlanMeal.slot == "dinner"
            )
            .values(recipe_id=satay)
        )
        allergies = await session.get(db.Allergies, world.user_id)
        assert allergies is not None
        allergies.allergens = ["peanuts"]
        await session.commit()
    v1 = await world.plan()

    # No local time: nothing today counts as eaten, so all of today is planned again.
    out = await world.say(swap(THU, D), planner=planner, local_time=None)

    assert out.results[0].status == "applied"
    v2 = await world.plan()
    assert past_rows(v2) == past_rows(v1)
    mon = meal(v2, MON, D)
    assert mon is not None
    assert mon.recipe_id == satay


async def test_shopping_ticks_survive_a_replan(world: World) -> None:
    async with world.maker() as session:
        await session.execute(
            update(db.ShoppingItem).where(db.ShoppingItem.plan_id == world.v1).values(checked=True)
        )
        await session.commit()
    before = {s.food_id: s.grams for s in (await world.plan()).shopping}

    await world.say(craving(FRI, D, "lasagne"))

    after = (await world.plan()).shopping
    assert after
    for line in after:
        kept = line.food_id in before and line.grams <= before[line.food_id]
        assert line.checked == kept, line.food_id
    assert any(line.checked for line in after)


@pytest.mark.parametrize("past", [False, True], ids=["replanned", "copied"])
async def test_shopping_ticks_made_while_replanning_survive(
    world: World, monkeypatch: pytest.MonkeyPatch, past: bool
) -> None:
    before = {s.food_id: s.grams for s in (await world.plan()).shopping}
    lock = planning.lock_user_plans

    async def tick_then_lock(session: AsyncSession, user_id: int) -> None:
        async with world.maker() as other:  # the user ticks the list meanwhile
            await other.execute(
                update(db.ShoppingItem)
                .where(db.ShoppingItem.plan_id == world.v1)
                .values(checked=True)
            )
            await other.commit()
        await lock(session, user_id)

    monkeypatch.setattr(planning, "lock_user_plans", tick_then_lock)

    await world.say(skip(TUE, D, elsewhere=False) if past else craving(FRI, D, "lasagne"))

    after = (await world.plan()).shopping
    assert after
    for line in after:
        kept = line.food_id in before and line.grams <= before[line.food_id]
        assert line.checked == kept, line.food_id


async def test_the_same_change_twice_for_one_message_is_applied_once(world: World) -> None:
    mid = uuid.uuid4()
    lasagne = craving(FRI, D, "lasagne")

    first = await world.say(lasagne, lasagne, request=mid)
    again = await world.say(lasagne, request=mid)

    assert [r.status for r in first.results] == ["applied", "unchanged"]
    assert [r.status for r in again.results] == ["unchanged"]
    assert again.plan_id is None
    assert await world.versions() == 2
    assert len(await world.cravings()) == 1

    pizza_mid = uuid.uuid4()
    await world.say(PIZZA_SLICES, request=pizza_mid)
    await world.say(PIZZA_SLICES, request=pizza_mid)
    assert len(await world.logs()) == 1


# --- the plan the changes apply to ------------------------------------------------------------


async def test_a_plan_changed_meanwhile_is_rebuilt_once(
    world: World, make_plan: Callable[[int, date], Coroutine[Any, Any, int]]
) -> None:
    interfered: list[int] = []

    def interfering(problem: Problem, previous: Plan | None) -> PlanResult:
        if not interfered:  # someone makes a new version while the first run is going
            interfered.append(anyio.from_thread.run(make_plan, world.user_id, MON))
        return greedy(problem, previous)

    out = await world.say(craving(FRI, D, "lasagne"), planner=interfering)

    assert out.results[0].status == "applied"
    v3 = await world.plan()
    assert (v3.version, v3.parent_id) == (3, interfered[0])
    assert world.runs == [2]


async def test_a_meal_marked_eaten_meanwhile_is_rebuilt_once(world: World) -> None:
    """Marking a meal eaten makes no version, so the plan id alone can't tell: the active logs
    are compared under the lock too, and the replan is rebuilt around the mark."""
    marked: list[int] = []

    async def mark_lunch() -> None:
        async with world.maker() as session:
            await eaten.mark(
                session, world.user_id, world.v1, TODAY, L, datetime(2026, 10, 14, 12, tzinfo=UTC)
            )

    def interfering(problem: Problem, previous: Plan | None) -> PlanResult:
        if not marked:
            anyio.from_thread.run(mark_lunch)
            marked.append(1)
        return greedy(problem, previous)

    out = await world.say(craving(FRI, D, "lasagne"), planner=interfering)

    assert out.results[0].status == "applied"
    assert world.runs == [2]
    v1, v2 = await world.plan(world.v1), await world.plan()
    before, after = meal(v1, TODAY, L), meal(v2, TODAY, L)
    assert before is not None
    assert after is not None
    assert (after.recipe_id, after.status) == (before.recipe_id, "eaten")
    assert total(v2, TODAY) == meals_kcal(v2, TODAY)
    assert logged(v2, TODAY) == []


async def test_a_plan_that_keeps_changing_fails_the_wishes_but_logs_the_facts(
    world: World, make_plan: Callable[[int, date], Coroutine[Any, Any, int]]
) -> None:
    def interfering(problem: Problem, previous: Plan | None) -> PlanResult:
        anyio.from_thread.run(make_plan, world.user_id, MON)
        return greedy(problem, previous)

    out = await world.say(PIZZA_SLICES, craving(FRI, D, "lasagne"), planner=interfering)

    assert out.results[1].status == "failed"
    assert "changed while I was working" in out.results[1].message
    assert out.plan_id is None
    [log] = await world.logs()
    assert log.voided_at is None


async def test_a_wish_after_the_plan_ends_fails(world: World) -> None:
    out = await world.say(craving(NEXT_MON, D, "lasagne"))

    assert out.results[0].status == "failed"
    assert "isn't in your plan yet" in out.results[0].message
    assert await world.versions() == 1


async def test_a_wish_when_no_plan_covers_today_starts_a_fresh_week(make_world: MakeWorld) -> None:
    world = await make_world(start=MON - timedelta(days=7))
    old = await world.plan()

    out = await world.say(craving(TODAY, D, "lasagne"))

    assert out.fresh
    assert out.results[0].status == "applied"
    fresh = await world.plan()
    assert (fresh.start_date, fresh.days, fresh.version, fresh.parent_id) == (TODAY, 7, 1, old.id)
    dinner = meal(fresh, TODAY, D)
    assert dinner is not None
    assert dinner.recipe_id == world.recipes["Lasagne"]


async def test_a_failed_fresh_week_still_logs_a_past_day_of_the_old_plan(
    make_world: MakeWorld,
) -> None:
    world = await make_world(start=MON - timedelta(days=7))
    old = await world.plan()
    last_fri = FRI - timedelta(days=7)

    out = await world.say(
        ate(last_fri, D, "2 slices of pizza", ("pizza", "2 slices")), craving(TODAY, D, "zorblax")
    )

    assert [r.status for r in out.results] == ["applied", "failed"]
    assert out.plan_id is None
    assert await world.versions() == 1
    [log] = await world.logs()
    assert (log.eaten_on, log.plan_id) == (last_fri, old.id)
    assert [c.status for c in await world.cravings()] == ["applied", "failed"]


async def test_goals_needing_review_fail_every_change_but_log_the_facts(
    make_world: MakeWorld,
) -> None:
    world = await make_world(kcal=(1200, 1300))
    async with world.maker() as session:
        session.add(
            db.BodyProfile(
                user_id=world.user_id,
                sex="male",
                birth_year=1996,
                height_cm=190,
                weight_kg=110,
                activity="very_active",
            )
        )
        await session.commit()

    out = await world.say(PIZZA_SLICES, craving(FRI, D, "lasagne"))

    assert [r.status for r in out.results] == ["failed", "failed"]
    assert all("review your goals" in r.message for r in out.results)
    assert out.plan_id is None
    assert await world.versions() == 1
    [log] = await world.logs()
    assert log.plan_id == world.v1


# --- planner runs -----------------------------------------------------------------------------


async def test_at_most_three_planner_runs(make_world: MakeWorld) -> None:
    # (a) everything and (b) without the soft wish both fail on Thursday; (c) facts only works.
    world = await make_world(kcal=(1500, 1900), protein=None)

    out = await world.say(
        craving(THU, D, "feast"),
        craving(FRI, D, "feast", strength="soft"),
        skip(SAT, L, elsewhere=True),
        planner=strict,
    )

    assert world.runs == [3]
    assert [r.status for r in out.results] == ["failed", "failed", "applied"]
    assert out.plan_id is not None


async def test_unrelated_days_keep_their_meals(world: World) -> None:
    v1 = await world.plan()

    await world.say(swap(THU, D))

    v2 = await world.plan()
    for on in (TODAY, FRI, SAT, SUN):
        assert {s: r for s, (r, _) in day_meals(v2, on).items()} == {
            s: r for s, (r, _) in day_meals(v1, on).items()
        }, on


def test_a_wish_never_sets_its_own_days_calorie_band() -> None:
    """Breakfast is over (400 kcal, locked empty): the day's band is relaxed only as far as its
    open meals' candidates can't reach it - two broth cravings don't drag it under the floor."""
    broth = Recipe(9, "Broth", frozenset({L, D}), Macros(80))
    recipes = {
        1: Recipe(1, "Porridge", frozenset({B}), Macros(400)),
        2: Recipe(2, "Stew", frozenset({L, D}), Macros(600)),
        3: Recipe(3, "Apple", frozenset({S}), Macros(120)),
        9: broth,
    }
    problem = Problem(
        start=TODAY,
        days=1,
        slots=(
            SlotSpec(B, True, (1,)),
            SlotSpec(L, True, (2,), max_portions=2),
            SlotSpec(D, True, (2,), max_portions=2),
            SlotSpec(S, False, (3,), max_portions=1),
        ),
        recipes=recipes,
        foods={},
        targets=Targets(daily={Nutrient.KCAL: Band(1600, 2200)}, calorie_floor=1200),
        locked={(0, B): None},
        extra={0: Macros(400)},
        choices={(0, L): (9,), (0, D): (9,)},
    )

    assert planning.day_bands(problem) == {0: Band(1600, 2200)}
    lunch_out = replace(problem, locked={(0, B): None, (0, L): None}, choices={(0, D): (9,)})
    assert planning.day_bands(lunch_out) == {0: Band(1600, 2200)}  # 400 + 1,200 + 120 reach it
    no_mains = replace(problem, locked={(0, B): None, (0, L): None, (0, D): None}, choices={})
    assert planning.day_bands(no_mains) == {0: Band(520, 2200)}  # a reported day: 400 + 120


# --- today's meals that are over, and pinned meals --------------------------------------------


async def test_meals_already_over_today_are_kept_as_they_were(world: World) -> None:
    v1 = await world.plan()

    out = await world.say(craving(FRI, D, "lasagne"), local_time=time(21, 0))

    assert out.results[0].status == "applied"
    v2 = await world.plan()
    assert day_meals(v2, TODAY) == day_meals(v1, TODAY)
    assert total(v2, TODAY) == meals_kcal(v2, TODAY)
    late = await world.say(craving(TODAY, D, "curry"), local_time=time(21, 0))
    assert late.results[0].status == "failed"
    assert "already over" in late.results[0].message


async def test_without_a_local_time_meals_before_the_one_named_count_as_eaten(
    world: World,
) -> None:
    v1 = await world.plan()

    await world.say(ate(TODAY, D, "a takeaway curry"), local_time=None)

    v2 = await world.plan()
    for slot in ("breakfast", "lunch"):
        assert day_meals(v2, TODAY).get(slot) == day_meals(v1, TODAY).get(slot)
    assert meal(v2, TODAY, D) is None


async def test_pinned_meals_stay_through_later_changes(world: World) -> None:
    await world.say(craving(THU, D, "lasagne"))

    out = await world.say(skip(SAT, L, elsewhere=True), swap(FRI, D))

    assert [r.status for r in out.results] == ["applied", "applied"]
    v3 = await world.plan()
    thu = meal(v3, THU, D)
    assert thu is not None
    assert (thu.recipe_id, thu.locked) == (world.recipes["Lasagne"], True)


async def test_a_pinned_meal_outlives_a_soft_wish_for_it_that_fails(
    make_world: MakeWorld,
) -> None:
    world = await make_world(kcal=(1500, 1700), protein=None)
    async with world.maker() as session:
        await session.execute(
            update(db.PlanMeal)
            .where(db.PlanMeal.plan_id == world.v1, db.PlanMeal.day == 3, db.PlanMeal.slot == D)
            .values(locked=True)
        )
        await session.commit()
    pinned = meal(await world.plan(), THU, D)
    assert pinned is not None

    out = await world.say(
        craving(THU, D, "feast", strength="soft"), skip(FRI, D, elsewhere=False), planner=strict
    )

    assert [r.status for r in out.results] == ["failed", "applied"]
    assert world.runs == [2]
    thu = meal(await world.plan(), THU, D)
    assert thu is not None
    assert (thu.recipe_id, thu.locked) == (pinned.recipe_id, True)


async def test_a_pinned_meal_that_is_no_longer_safe_is_dropped(world: World) -> None:
    await world.say(craving(THU, D, "satay"))
    async with world.maker() as session:
        allergies = await session.get(db.Allergies, world.user_id)
        assert allergies is not None
        allergies.allergens = ["peanuts"]
        await session.commit()

    out = await world.say(swap(FRI, D))

    assert any("Satay rice" in note for note in out.notes)
    thu = meal(await world.plan(), THU, D)
    assert thu is not None
    assert thu.recipe_id != world.recipes["Satay rice"]
    assert not thu.locked


async def test_several_foods_reported_for_one_meal_are_all_logged(world: World) -> None:
    out = await world.say(PIZZA_SLICES, ate(TODAY, L, "a latte"))

    assert [r.status for r in out.results] == ["applied", "applied"]
    assert [log.description for log in await world.logs()] == ["2 slices of pizza", "a latte"]
    assert logged(await world.plan(), TODAY) == ["2 slices of pizza", "a latte"]


# --- what the plan API shows ------------------------------------------------------------------


async def test_the_plan_api_shows_logged_food_and_the_parent(
    world: World, api: httpx.AsyncClient, auth: Callable[..., dict[str, str]]
) -> None:
    await world.say(PIZZA_SLICES)

    plan = (await api.get("/plans/current", headers=auth("user_a"))).json()

    assert (plan["version"], plan["parent_id"]) == (2, world.v1)
    wednesday = plan["days"][2]
    assert [e["description"] for e in wednesday["logged"]] == ["2 slices of pizza"]
    meals = sum(m["nutrition"]["kcal"] for m in wednesday["meals"])
    assert wednesday["totals"]["kcal"] == meals + PIZZA_SLICES_KCAL
    assert "lunch" not in {m["slot"] for m in wednesday["meals"]}
    assert all(d["logged"] == [] for i, d in enumerate(plan["days"]) if i != 2)


async def test_plans_saved_before_replans_still_load(world: World) -> None:
    v1 = await world.plan()
    old = dict(v1.stats) | {"v": 1}
    old.pop("logged", None)
    old.pop("outcome", None)

    stats = planning.PlanStats.model_validate(old)

    assert (stats.v, stats.logged_on(0), stats.outcome) == (1, [], None)


CPSAT: planning.Planner = partial(planning.run_planner, mode="auto", time_limit_ms=1000, workers=2)


@pytest.mark.parametrize("planner", [GREEDY, CPSAT], ids=["greedy", "cpsat"])
async def test_cook_extra_keeps_tonights_dinner(world: World, planner: planning.Planner) -> None:
    """ "Cook extra for tomorrow's lunch" (the plan page) swaps tomorrow's lunch to tonight's
    dinner and tonight's dinner to itself, so the planner can't move tonight's dinner to make
    room (CP-SAT would, when that balances the day better)."""
    v1 = await world.plan()
    dinner = meal(v1, TODAY, D)
    assert dinner is not None
    rid = dinner.recipe_id

    out = await world.say(
        swap(TODAY, D, recipe_id=rid), swap(THU, L, recipe_id=rid), planner=planner
    )

    assert [r.status for r in out.results] == ["applied", "applied"], out.results
    assert out.results[0].message == f"Wed dinner stays {world.name(rid)}."
    assert out.results[1].message == f"Thu lunch is now {world.name(rid)}."
    v2 = await world.plan()
    lunch, kept = meal(v2, THU, L), meal(v2, TODAY, D)
    assert lunch is not None
    assert kept is not None
    assert lunch.recipe_id == dinner.recipe_id
    assert kept.recipe_id == dinner.recipe_id
