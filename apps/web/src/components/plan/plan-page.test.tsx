import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Plan } from "@/lib/api/hooks";
import { deferred, json, mockApi, renderWithClient, type Routes } from "@/test/api";
import { makePlan, ME, meal } from "@/test/fixtures";
import { calls as nav, currentUrl, resetNavigation } from "@/test/navigation";

import { PlanPage, planEnded } from "./plan-page";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => import("@/test/navigation"));

const ALLERGENS = [{ code: "peanuts", label: "Peanuts" }];

function setup(routes: Routes) {
  const calls = mockApi({ "GET /me": json(ME), "GET /allergens": json(ALLERGENS), ...routes });
  renderWithClient(<PlanPage />);
  return calls;
}

function today(y: number, m: number, d: number) {
  vi.setSystemTime(new Date(y, m - 1, d, 10, 0));
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  today(2026, 10, 9);
  resetNavigation("/plan");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("planEnded", () => {
  it("is true once the last day has passed", () => {
    const plan = makePlan();
    expect(planEnded(plan, "2026-10-15")).toBe(false);
    expect(planEnded(plan, "2026-10-16")).toBe(true);
    expect(planEnded(plan, "2026-10-08")).toBe(false);
  });
});

describe("PlanPage states", () => {
  it("asks to finish setup first", async () => {
    setup({
      "GET /me": json({ ...ME, setup_complete: false }),
      "GET /plans/current": json(null),
    });

    expect(await screen.findByText(/Finish setting up/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up" })).toHaveAttribute("href", "/setup");
    expect(screen.queryByRole("button", { name: "Plan my week" })).not.toBeInTheDocument();
  });

  it("plans the first week from the local date", async () => {
    const calls = setup({
      "GET /plans/current": json(null),
      "POST /plans": json(makePlan(), 201),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Plan my week" }));

    expect(await screen.findByText("Breakfast 1")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ start: "2026-10-09" });
    expect(toast.success).toHaveBeenCalled();
  });

  it("shows that planning is under way and blocks a second request", async () => {
    const reply = deferred<Response>();
    const calls = setup({
      "GET /plans/current": json(null),
      "POST /plans": () => reply.promise,
    });

    fireEvent.click(await screen.findByRole("button", { name: "Plan my week" }));

    const busy = await screen.findByRole("button", { name: "Planning…" });
    expect(busy).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("takes a few seconds");
    fireEvent.click(busy);
    reply.resolve(Response.json(makePlan(), { status: 201 }));
    expect(await screen.findByText("Breakfast 1")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
  });

  it.each([400, 409, 503])("lists the API's reasons on %d", async (status) => {
    setup({
      "GET /plans/current": json(null),
      "POST /plans": json(
        { detail: ["Only 3 breakfasts fit your allergies", "Try widening your calorie range"] },
        status,
      ),
    });

    fireEvent.click(await screen.findByRole("button", { name: "Plan my week" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Only 3 breakfasts fit your allergies");
    expect(alert).toHaveTextContent("Try widening your calorie range");
    const review = screen.queryByRole("link", { name: "Review your profile" });
    if (status === 409) expect(review).toHaveAttribute("href", "/profile");
    else expect(review).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Plan my week" })).toBeEnabled();
  });

  it("offers a fresh plan when the current one has ended", async () => {
    today(2026, 10, 20);
    const next = makePlan({ id: 8, start: "2026-10-20" });
    const calls = setup({
      "GET /plans/current": json(makePlan()),
      "POST /plans": json(next, 201),
    });

    expect(await screen.findByText("This plan ended on Thursday 15 October")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New plan" })).not.toBeInTheDocument();
    // An ended plan still opens on its first day.
    expect(screen.getByRole("tab", { name: "Fri 9 October" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.click(screen.getByRole("button", { name: "Plan this week" }));

    await waitFor(() => expect(screen.queryByText(/This plan ended/)).not.toBeInTheDocument());
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ start: "2026-10-20" });
    expect(screen.getByRole("tab", { name: "Today 20 October" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});

describe("loaded plan", () => {
  it("shows exclusions, today's meals and the day's macros", async () => {
    today(2026, 10, 10);
    setup({ "GET /plans/current": json(makePlan()) });

    const without = await screen.findByRole("list", { name: "Planned without:" });
    expect(
      within(without)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["Peanuts", "Vegetarian"]);

    const strip = screen.getByRole("tablist", { name: "Day" });
    expect(within(strip).getAllByRole("tab")).toHaveLength(7);
    expect(within(strip).getByRole("tab", { name: "Today 10 October" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    const meals = screen.getByRole("list", { name: "Meals on Saturday 10 October" });
    const links = within(meals).getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/recipes/101",
      "/recipes/201",
      "/recipes/301",
    ]);
    expect(links[0]).toHaveTextContent("Breakfast");
    expect(links[0]).toHaveTextContent("Breakfast 2");
    expect(links[0]).toHaveTextContent("×1½");
    expect(links[0]).toHaveTextContent("600 kcal · 30 g protein");
    expect(within(meals).getAllByTestId("meal-placeholder")).toHaveLength(3);

    expect(screen.getByRole("meter", { name: "Calories" })).toHaveAttribute(
      "aria-valuenow",
      "1900",
    );
    expect(screen.getByRole("meter", { name: "Protein" })).toBeInTheDocument();
  });

  it("lazy-loads meal photos", async () => {
    setup({ "GET /plans/current": json(makePlan()) });

    const meals = await screen.findByRole("list", { name: "Meals on Friday 9 October" });
    const img = meals.querySelector("img");
    expect(img).toHaveAttribute("src", "https://img.example/b1.jpg");
    expect(img).toHaveAttribute("loading", "lazy");
    expect(within(meals).getAllByTestId("meal-placeholder")).toHaveLength(2);
  });

  it("switches days through the URL", async () => {
    setup({ "GET /plans/current": json(makePlan()) });

    fireEvent.click(await screen.findByRole("tab", { name: "Sun 11 October" }));

    expect(await screen.findByText("Breakfast 3")).toBeInTheDocument();
    expect(currentUrl()).toBe("/plan?day=2026-10-11");
    expect(screen.queryByText("Breakfast 1")).not.toBeInTheDocument();
  });

  it("opens on the day in the URL", async () => {
    resetNavigation("/plan?day=2026-10-13");
    setup({ "GET /plans/current": json(makePlan()) });

    expect(await screen.findByText("Breakfast 5")).toBeInTheDocument();
  });

  it("toggles between the day and a compact week grid", async () => {
    const plan = makePlan();
    plan.days[2].meals.push(meal("snack", 400, "Hummus and carrots", { portions: 1 }));
    setup({ "GET /plans/current": json(plan) });

    fireEvent.click(await screen.findByRole("tab", { name: "Week" }));

    const grid = await screen.findByRole("table", { name: "Meals this week" });
    expect(currentUrl()).toBe("/plan?view=week");
    expect(
      within(grid)
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual(["Day", "Breakfast", "Lunch", "Dinner", "Snack"]);
    const rows = within(grid).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(7);
    expect(within(rows[2]).getByRole("link", { name: "Hummus and carrots" })).toHaveAttribute(
      "href",
      "/recipes/400",
    );
    expect(within(rows[0]).getByText("No snack")).toBeInTheDocument();
    expect(within(rows[0]).getByRole("rowheader")).toHaveTextContent("Fri 91,900 kcal");

    fireEvent.click(within(rows[3]).getByRole("button", { name: "Open Mon 12" }));

    expect(await screen.findByText("Breakfast 4")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(currentUrl()).toBe("/plan?day=2026-10-12");
  });

  it("summarises the week: energy, protein, cost against budget, pantry and waste", async () => {
    setup({ "GET /plans/current": json(makePlan({ waste_g: 150 })) });

    const summary = await screen.findByRole("region", { name: "This plan" });
    expect(summary).toHaveTextContent("1,900 kcal");
    expect(summary).toHaveTextContent("≈ £42.10");
    expect(summary).toHaveTextContent("budget £50.00");
    expect(summary).toHaveTextContent("1.2 kg");
    expect(summary).toHaveTextContent("150 g");
    expect(within(summary).getByRole("meter", { name: "Protein over 7 days" })).toHaveAttribute(
      "aria-valuetext",
      "665 g, target ≥ 630 g",
    );
  });

  it("flags a plan over budget", async () => {
    setup({
      "GET /plans/current": json(
        makePlan({ cost_minor: 5320, currency: "EUR", budget_minor: 5000 }),
      ),
    });

    const summary = await screen.findByRole("region", { name: "This plan" });
    expect(summary).toHaveTextContent("≈ €53.20");
    expect(summary).toHaveTextContent("€3.20 over your €50.00 budget");
  });
});

describe("violations and planner notes", () => {
  const violations: Plan["violations"] = [
    {
      code: "daily_band",
      message: "Tue: 2,350 kcal is above your 2,200 kcal maximum",
      hard: true,
      day: 4,
    },
    { code: "daily_band", message: "Wed: 60 g protein is below 72 g", hard: false, day: 5 },
  ];

  it("separates hard misses (warning) from soft trade-offs (info)", async () => {
    setup({
      "GET /plans/current": json(
        makePlan({ planner: "greedy", violations, notes: ["The optimiser timed out."] }),
      ),
    });

    const hard = await screen.findByTestId("hard-violations");
    expect(hard).toHaveTextContent("Quick planner couldn't meet:");
    expect(hard).toHaveTextContent("Tue: 2,350 kcal is above your 2,200 kcal maximum");
    expect(hard).not.toHaveTextContent("protein");
    expect(hard.className).toContain("amber");

    const soft = screen.getByTestId("soft-violations");
    expect(soft).toHaveTextContent("Trade-offs in this plan");
    expect(soft).toHaveTextContent("Wed: 60 g protein is below 72 g");

    const note = screen.getByTestId("planner-note");
    expect(note).toHaveTextContent("quick planner");
    expect(note).toHaveTextContent("The optimiser timed out.");
  });

  it("shows no banners for a clean optimised plan", async () => {
    setup({ "GET /plans/current": json(makePlan()) });

    await screen.findByText("Breakfast 1");
    expect(screen.queryByTestId("hard-violations")).not.toBeInTheDocument();
    expect(screen.queryByTestId("soft-violations")).not.toBeInTheDocument();
    expect(screen.queryByTestId("planner-note")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("New plan", () => {
  it("confirms, stays disabled while planning, then shows the new plan", async () => {
    resetNavigation("/plan?day=2026-10-12&view=week");
    const next = makePlan({ id: 8, version: 2 });
    next.days[0].meals[0] = meal("breakfast", 900, "Shakshuka");
    const reply = deferred<Response>();
    const calls = setup({
      "GET /plans/current": json(makePlan()),
      "POST /plans": () => reply.promise,
    });

    const newPlan = await screen.findByRole("button", { name: "New plan" });
    fireEvent.click(newPlan);
    expect(newPlan).toHaveAttribute("aria-expanded", "true");
    const confirm = screen.getByRole("group", { name: "Confirm new plan" });
    expect(confirm).toHaveTextContent("Replaces this plan. Shopping ticks reset.");
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    fireEvent.click(within(confirm).getByRole("button", { name: "Replace plan" }));

    expect(await within(confirm).findByRole("button", { name: "Planning…" })).toBeDisabled();
    expect(within(confirm).getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "New plan" })).toBeDisabled();

    reply.resolve(Response.json(next, { status: 201 }));

    expect(await screen.findByText("Shakshuka")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Confirm new plan" })).not.toBeInTheDocument();
    expect(nav.replace.at(-1)).toBe("/plan");
  });

  it("can be cancelled", async () => {
    const calls = setup({ "GET /plans/current": json(makePlan()) });

    fireEvent.click(await screen.findByRole("button", { name: "New plan" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("group", { name: "Confirm new plan" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("keeps the current plan and shows reasons when replanning fails", async () => {
    setup({
      "GET /plans/current": json(makePlan()),
      "POST /plans": json({ detail: ["The planner found no plan in time"] }, 503),
    });

    fireEvent.click(await screen.findByRole("button", { name: "New plan" }));
    fireEvent.click(screen.getByRole("button", { name: "Replace plan" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("found no plan in time");
    expect(screen.getByText("Breakfast 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace plan" })).toBeEnabled();
  });
});
