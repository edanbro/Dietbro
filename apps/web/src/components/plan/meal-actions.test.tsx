import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatOutcome, Eaten, Plan } from "@/lib/api/hooks";
import { deferred, json, mockApi, renderWithClient, type Routes } from "@/test/api";
import { makePlan, ME } from "@/test/fixtures";
import { resetNavigation } from "@/test/navigation";

import { eatenMessage, tradesFor } from "./meal-actions";
import { PlanPage } from "./plan-page";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => import("@/test/navigation"));

const FRIDAY = "Meals on Friday 9 October";

function setup(routes: Routes) {
  const calls = mockApi({ "GET /me": json(ME), "GET /allergens": json([]), ...routes });
  renderWithClient(<PlanPage />);
  return calls;
}

function eatenOut(overrides: Partial<Eaten> = {}): Eaten {
  return {
    plan_id: 7,
    date: "2026-10-09",
    slot: "breakfast",
    status: "eaten",
    changed: true,
    meal: null,
    pantry: [
      {
        pantry_item_id: 1,
        food_id: 11,
        name: "Chickpeas",
        grams: 200,
        quantity: 200,
        unit: "g",
        remaining_quantity: 200,
      },
    ],
    notes: [],
    ...overrides,
  };
}

function withEatenBreakfast(): Plan {
  const plan = makePlan();
  plan.days[0].meals[0] = { ...plan.days[0].meals[0], status: "eaten" };
  return plan;
}

/** The options of a meal on a day, opened. */
async function openOptions(day: string, slot: string) {
  const list = await screen.findByRole("list", { name: day });
  fireEvent.click(within(list).getByRole("button", { name: `${slot} options` }));
  return screen.getByRole("group", { name: `${slot} options` });
}

function names(group: HTMLElement) {
  return within(group)
    .getAllByRole("button")
    .map((b) => b.textContent);
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 9, 10, 0));
  resetNavigation("/plan");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("meal options", () => {
  it("offers today's actions and closes again", async () => {
    setup({ "GET /plans/current": json(makePlan()) });

    const list = await screen.findByRole("list", { name: FRIDAY });
    const toggle = within(list).getByRole("button", { name: "Lunch options" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const group = screen.getByRole("group", { name: "Lunch options" });
    expect(names(group)).toEqual([
      "Mark eaten",
      "Skip",
      "Swap for something else",
      "Swap with another day",
      "Had something else",
    ]);
    // The recipe stays a link next to the options.
    expect(within(list).getByRole("link", { name: /Lunch 1/ })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/recipes\/200(\?|$)/),
    );

    fireEvent.click(toggle);
    expect(screen.queryByRole("group", { name: "Lunch options" })).not.toBeInTheDocument();
  });

  it("only marks past meals eaten, and never future ones", async () => {
    vi.setSystemTime(new Date(2026, 9, 10, 10, 0));
    setup({ "GET /plans/current": json(makePlan()) });

    fireEvent.click(await screen.findByRole("tab", { name: "Fri 9 October" }));
    expect(names(await openOptions(FRIDAY, "Dinner"))).toEqual(["Mark eaten"]);

    fireEvent.click(screen.getByRole("tab", { name: "Sun 11 October" }));
    expect(names(await openOptions("Meals on Sunday 11 October", "Dinner"))).toEqual([
      "Skip",
      "Swap for something else",
      "Swap with another day",
      "Cook extra for tomorrow's lunch",
    ]);
  });

  it("swaps a meal with the same meal on another day, as one change", async () => {
    const plan = makePlan();
    const calls = setup({
      "GET /plans/current": json(plan),
      "POST /plans/replan": json({ type: "outcome", results: [], changes: [] }),
    });

    const group = await openOptions(FRIDAY, "Dinner");
    fireEvent.click(within(group).getByRole("button", { name: "Swap with another day" }));
    const choices = within(group).getByRole("group", { name: "Swap dinner with the one on:" });
    // Fri 9 is this one; the other six days, each with its dinner.
    expect(within(choices).getAllByRole("button", { name: /^\w{3} \d+/ })).toHaveLength(6);
    fireEvent.click(within(choices).getByRole("button", { name: "Sun 11 Dinner 3" }));

    await waitFor(() => expect(calls.some((c) => c.path === "/plans/replan")).toBe(true));
    const body = calls.find((c) => c.path === "/plans/replan")!.body as { changes: unknown[] };
    expect(body.changes).toEqual([
      { intent: "swap", when: { date: "2026-10-09", slot: "dinner" }, recipe_id: 302 },
      { intent: "swap", when: { date: "2026-10-11", slot: "dinner" }, recipe_id: 300 },
    ]);
  });

  it("cooks tonight's dinner in double for tomorrow's lunch", async () => {
    vi.setSystemTime(new Date(2026, 9, 10, 10, 0));
    const plan = makePlan();
    const calls = setup({
      "GET /plans/current": json(plan),
      "POST /plans/replan": json({ type: "outcome", results: [], changes: [] }),
    });

    fireEvent.click(await screen.findByRole("tab", { name: "Sun 11 October" }));
    const group = await openOptions("Meals on Sunday 11 October", "Dinner");
    fireEvent.click(within(group).getByRole("button", { name: "Cook extra for tomorrow's lunch" }));

    await waitFor(() => expect(calls.some((c) => c.path === "/plans/replan")).toBe(true));
    const body = calls.find((c) => c.path === "/plans/replan")!.body as {
      changes: { intent: string; when: { date: string; slot: string }; recipe_id: number }[];
    };
    const sunday = plan.days.find((d) => d.date === "2026-10-11")!;
    const dinner = sunday.meals.find((m) => m.slot === "dinner")!;
    expect(body.changes).toEqual([
      {
        intent: "swap",
        when: { date: "2026-10-12", slot: "lunch" },
        recipe_id: dinner.recipe.id,
      },
    ]);
  });

  it("marks a meal eaten, says what came out of the pantry and reloads the plan", async () => {
    let plan = makePlan();
    const reply = deferred<Response>();
    const calls = setup({
      "GET /plans/current": () => Response.json(plan),
      "POST /plans/7/meals/eaten": () => reply.promise,
    });

    const group = await openOptions(FRIDAY, "Breakfast");
    fireEvent.click(within(group).getByRole("button", { name: "Mark eaten" }));

    // Pending: every action waits, and it is announced.
    await waitFor(() =>
      expect(within(group).getByRole("button", { name: "Skip" })).toBeDisabled(),
    );
    expect(within(group).getByRole("status")).toHaveTextContent("Updating your plan");
    const list = screen.getByRole("list", { name: FRIDAY });
    expect(within(list).getByRole("button", { name: "Lunch options" })).toBeEnabled();

    plan = withEatenBreakfast();
    reply.resolve(Response.json(eatenOut()));

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(toast.success).toHaveBeenCalledWith("Breakfast marked eaten", {
      description: "Took 200 g chickpeas from your pantry.",
    });
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      today: "2026-10-09",
      date: "2026-10-09",
      slot: "breakfast",
    });
    const card = await within(list).findByRole("link", { name: /Breakfast 1/ });
    await waitFor(() => expect(card).toHaveTextContent("BreakfastEaten"));
    expect(screen.queryByRole("group", { name: "Breakfast options" })).not.toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/plans/current")).toHaveLength(2);
    expect(calls.some((c) => c.path === "/pantry")).toBe(false); // not on screen, only marked stale
  });

  it("only offers undo on an eaten meal, and undoes it", async () => {
    const urls: string[] = [];
    setup({
      "GET /plans/current": json(withEatenBreakfast()),
      "DELETE /plans/7/meals/eaten": (req) => {
        urls.push(req.url);
        return Response.json(
          eatenOut({
            status: "planned",
            pantry: [
              { ...eatenOut().pantry[0], name: "Oats", grams: 80 },
              { ...eatenOut().pantry[0], name: "Gone", remaining_quantity: null },
            ],
            notes: ["Gone was deleted from your pantry, so it wasn't put back."],
          }),
        );
      },
    });

    const group = await openOptions(FRIDAY, "Breakfast");
    expect(names(group)).toEqual(["Undo eaten"]);
    fireEvent.click(within(group).getByRole("button", { name: "Undo eaten" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(new URL(urls[0]).search).toBe("?date=2026-10-09&slot=breakfast");
    expect(toast.success).toHaveBeenCalledWith("Breakfast no longer marked eaten", {
      description:
        "Put 80 g oats back in your pantry. " +
        "Gone was deleted from your pantry, so it wasn't put back.",
    });
  });

  it("reloads the plan when it changed elsewhere (409)", async () => {
    const calls = setup({
      "GET /plans/current": json(makePlan()),
      "POST /plans/7/meals/eaten": json({ detail: ["Plan 7 is not the latest version"] }, 409),
    });

    const group = await openOptions(FRIDAY, "Lunch");
    fireEvent.click(within(group).getByRole("button", { name: "Mark eaten" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Your plan changed in the meantime. Showing the latest version.",
      ),
    );
    await waitFor(() =>
      expect(calls.filter((c) => c.path === "/plans/current")).toHaveLength(2),
    );
    // Still open, ready to try again.
    expect(within(group).getByRole("button", { name: "Mark eaten" })).toBeEnabled();
  });
});

describe("replans from the plan", () => {
  const outcome: ChatOutcome = {
    type: "outcome",
    plan_id: 8,
    version: 2,
    fresh: false,
    results: [
      {
        index: 0,
        intent: "skip",
        date: "2026-10-09",
        slot: "dinner",
        status: "applied",
        message: "Skipped Fri dinner.",
      },
    ],
    changes: [
      { date: "2026-10-09", slot: "dinner", before: "Dinner 1", after: null, reason: "skip" },
      {
        date: "2026-10-09",
        slot: "lunch",
        before: "Lunch 1",
        after: "Lunch 1",
        before_portions: 2,
        after_portions: 3,
        reason: "resize",
      },
    ],
    logged: [
      {
        date: "2026-10-09",
        slot: "dinner",
        kind: "skipped",
        description: "",
        kcal: 0,
        estimated: true,
      },
    ],
    days: [],
    warnings: [],
    notes: [],
  };

  it("skips a meal, then shows what changed until dismissed", async () => {
    const reply = deferred<Response>();
    const calls = setup({
      "GET /plans/current": json(makePlan()),
      "POST /plans/replan": () => reply.promise,
    });

    const group = await openOptions(FRIDAY, "Dinner");
    fireEvent.click(within(group).getByRole("button", { name: "Skip" }));
    const question = within(group).getByRole("group", { name: "Eating somewhere else instead?" });
    expect(question).toBeVisible();
    fireEvent.click(within(group).getByRole("button", { name: "No, I'm not eating" }));

    await waitFor(() =>
      expect(within(group).getByRole("button", { name: "Back" })).toBeDisabled(),
    );
    reply.resolve(Response.json(outcome));

    const panel = await screen.findByRole("region", { name: "What changed" });
    expect(panel).toHaveFocus();
    expect(within(panel).getByRole("list", { name: "Requests" })).toHaveTextContent(
      "Done: Skipped Fri dinner.",
    );
    expect(
      within(within(panel).getByRole("list", { name: "Meal changes" }))
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "Today's dinner: Dinner 1 → no meal — you're skipping it",
      "Today's lunch: Lunch 1 (1 → 1½ servings) — portion resized to fit the day",
    ]);
    expect(within(panel).getByRole("list", { name: "Logged food" })).toHaveTextContent(
      "Skipped today's dinner",
    );

    const body = calls.find((c) => c.path === "/plans/replan")?.body as Record<string, unknown>;
    expect(body).toMatchObject({
      changes: [
        { intent: "skip", when: { date: "2026-10-09", slot: "dinner" }, eating_elsewhere: false },
      ],
      today: "2026-10-09",
      local_time: "10:00:00",
    });
    expect(body.client_id).toMatch(/^[0-9a-f-]{36}$/);
    await waitFor(() =>
      expect(calls.filter((c) => c.path === "/plans/current")).toHaveLength(2),
    );

    fireEvent.click(within(panel).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("region", { name: "What changed" })).not.toBeInTheDocument();
  });

  it("swaps a meal for a picked option and logs something else instead", async () => {
    const calls = setup({
      "GET /plans/current": json(makePlan()),
      "GET /plans/7/alternatives": json([
        {
          id: 300,
          name: "Lentil stew",
          category: null,
          cuisine: null,
          image_url: null,
          slots: ["lunch"],
          kcal_per_serving: 520,
          protein_g_per_serving: 30,
          uses_pantry: [],
          favourite: false,
        },
      ]),
      "POST /plans/replan": json(outcome),
    });

    let group = await openOptions(FRIDAY, "Lunch");
    fireEvent.click(within(group).getByRole("button", { name: "Swap for something else" }));
    fireEvent.click(await within(group).findByRole("button", { name: /Lentil stew/ }));
    await screen.findByRole("region", { name: "What changed" });

    group = await openOptions(FRIDAY, "Breakfast");
    fireEvent.click(within(group).getByRole("button", { name: "Had something else" }));
    const log = within(group).getByRole("button", { name: "Log it" });
    expect(log).toBeDisabled();
    fireEvent.change(within(group).getByRole("textbox", { name: "What did you have?" }), {
      target: { value: "  2 slices of pizza " },
    });
    fireEvent.click(log);

    await waitFor(() =>
      expect(calls.filter((c) => c.path === "/plans/replan")).toHaveLength(2),
    );
    const [swap, other] = calls
      .filter((c) => c.path === "/plans/replan")
      .map((c) => (c.body as { changes: unknown[] }).changes);
    expect(swap).toEqual([
      { intent: "swap", when: { date: "2026-10-09", slot: "lunch" }, recipe_id: 300 },
    ]);
    const asked = calls.find((c) => c.path === "/plans/7/alternatives");
    expect(asked).toBeDefined();
    expect(other).toEqual([
      {
        intent: "ate_off_plan",
        when: { date: "2026-10-09", slot: "breakfast" },
        description: "2 slices of pizza",
      },
    ]);
  });

  it("searches and filters what to swap a meal for", async () => {
    const asked: URLSearchParams[] = [];
    const stew = {
      id: 300,
      name: "Lentil stew",
      category: null,
      cuisine: null,
      image_url: null,
      slots: ["lunch"],
      kcal_per_serving: 520,
      protein_g_per_serving: 30,
      uses_pantry: [],
      favourite: false,
      minutes: 25,
    };
    setup({
      "GET /plans/current": json(makePlan()),
      "GET /plans/7/alternatives": (req) => {
        const params = new URL(req.url).searchParams;
        asked.push(params);
        return Response.json(params.get("q") === "zzz" ? [] : [stew]);
      },
    });

    const group = await openOptions(FRIDAY, "Lunch");
    fireEvent.click(within(group).getByRole("button", { name: "Swap for something else" }));
    expect(
      await within(group).findByRole("button", { name: /Lentil stew25 min · 520 kcal/ }),
    ).toBeVisible();
    fireEvent.click(within(group).getByRole("button", { name: "Quick" }));
    expect(within(group).getByRole("button", { name: "Quick" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await waitFor(() => expect(asked.at(-1)?.get("quick")).toBe("true"));
    fireEvent.click(within(group).getByRole("button", { name: "Favourites" }));
    await waitFor(() => expect(asked.at(-1)?.get("favourites")).toBe("true"));
    expect(asked.at(-1)?.get("limit")).toBe("6");
    fireEvent.change(within(group).getByRole("searchbox", { name: "Search recipes" }), {
      target: { value: "zzz" },
    });
    expect(
      await within(group).findByText("Nothing safe for you matches. Try other words."),
    ).toBeVisible();
    expect(asked.at(-1)?.get("q")).toBe("zzz");
  });

  it.each([
    ["busy", "Another change to your plan is still running. Try again in a moment."],
    ["duplicate", "That change was already made. Showing your latest plan."],
  ])("reloads the plan on 409 %s", async (code, message) => {
    const calls = setup({
      "GET /plans/current": json(makePlan()),
      "POST /plans/replan": json({ detail: ["nope"], code }, 409),
    });

    const group = await openOptions(FRIDAY, "Lunch");
    fireEvent.click(within(group).getByRole("button", { name: "Swap for something else" }));
    fireEvent.click(within(group).getByRole("button", { name: "Anything else - you pick" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(message));
    await waitFor(() =>
      expect(calls.filter((c) => c.path === "/plans/current")).toHaveLength(2),
    );
    expect(screen.queryByRole("region", { name: "What changed" })).not.toBeInTheDocument();
  });
});

describe("eaten meals in the plan", () => {
  it("shows an eaten log (a meal no longer planned) with its recipe", async () => {
    const plan = makePlan();
    plan.days[0].meals = plan.days[0].meals.filter((m) => m.slot !== "breakfast");
    plan.days[0].logged = [
      {
        date: "2026-10-09",
        slot: "breakfast",
        kind: "eaten",
        description: "porridge with berries",
        kcal: 420,
        estimated: false,
        recipe_id: 55,
      },
    ];
    setup({ "GET /plans/current": json(plan) });

    const list = await screen.findByRole("list", { name: FRIDAY });
    const link = within(list).getByRole("link", {
      name: "Porridge with berries (eaten, 420 kcal)",
    });
    expect(link).toHaveAttribute("href", "/recipes/55");
    expect(within(list).queryByText(/off-plan/)).not.toBeInTheDocument();
  });

  it("marks eaten meals in the week grid", async () => {
    resetNavigation("/plan?view=week");
    setup({ "GET /plans/current": json(withEatenBreakfast()) });

    const grid = await screen.findByRole("table", { name: "Meals this week" });
    expect(within(grid).getByRole("link", { name: "Breakfast 1 (eaten)" })).toBeInTheDocument();
  });
});

describe("eatenMessage", () => {
  it("says when nothing changed", () => {
    expect(eatenMessage(eatenOut({ changed: false }), false)).toEqual({
      title: "Breakfast was already marked eaten",
    });
  });

  it("lists several pantry foods", () => {
    const base = eatenOut().pantry[0];
    const out = eatenOut({
      slot: "dinner",
      pantry: [
        base,
        { ...base, name: "Rice", grams: 1000 },
        { ...base, name: "Spinach", grams: 50 },
      ],
      notes: [],
    });
    expect(eatenMessage(out, false)).toEqual({
      title: "Dinner marked eaten",
      description: "Took 200 g chickpeas, 1 kg rice and 50 g spinach from your pantry.",
    });
  });

  it("has no description without pantry food or notes", () => {
    expect(eatenMessage(eatenOut({ pantry: [] }), false)).toEqual({
      title: "Breakfast marked eaten",
      description: undefined,
    });
  });
});

describe("tradesFor", () => {
  it("finds the same meal on the other days still to come, not eaten, of another recipe", () => {
    const plan = makePlan();
    const [fri, sat, sun, mon] = plan.days;
    sat!.meals[2] = { ...sat!.meals[2]!, status: "eaten" };
    sun!.meals[2] = { ...sun!.meals[2]!, recipe: { ...sun!.meals[2]!.recipe, id: 301 } };
    const sundayDinner = sun!.meals[2]!;

    const trades = tradesFor(plan.days, sun!.date, sundayDinner, fri!.date);

    expect(trades.map((t) => t.date)).toEqual([
      fri!.date, // today counts
      mon!.date,
      ...plan.days.slice(4).map((d) => d.date),
    ]); // not Saturday (eaten), not Sunday itself
    expect(tradesFor(plan.days, fri!.date, fri!.meals[2]!, sat!.date)).not.toContainEqual(
      expect.objectContaining({ date: fri!.date }),
    );
    expect(trades.every((t) => t.meal.slot === "dinner")).toBe(true);
  });
});
