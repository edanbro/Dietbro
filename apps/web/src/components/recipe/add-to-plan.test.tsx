import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { localISODate } from "@/lib/dates";
import { json, mockApi, renderWithClient } from "@/test/api";
import { makePlan, makeRecipe } from "@/test/fixtures";

import { AddToPlan, planCells } from "./add-to-plan";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const today = localISODate();
const OTHER = makeRecipe({ id: 999, meal_types: ["breakfast", "lunch", "dinner"] });

describe("planCells", () => {
  const plan = makePlan({ start: today });

  it("offers only meals from today on that aren't eaten and that the recipe suits", () => {
    const dinnerOnly = makeRecipe({ id: 999, meal_types: ["dinner"] });
    const cells = planCells(plan, dinnerOnly, today);
    expect(cells.length).toBeGreaterThan(0);
    expect(cells.every((c) => c.slot === "dinner" && c.date >= today)).toBe(true);

    const eaten = structuredClone(plan);
    for (const meal of eaten.days[0].meals) meal.status = "eaten";
    expect(planCells(eaten, OTHER, today).every((c) => c.date !== eaten.days[0].date)).toBe(true);
  });

  it("leaves out the meals that already are this recipe", () => {
    const planned = plan.days[0].meals[0].recipe;
    const same = makeRecipe({ id: planned.id, meal_types: [plan.days[0].meals[0].slot] });
    const cells = planCells(plan, same, today);
    expect(cells.some((c) => c.date === plan.days[0].date && c.slot === plan.days[0].meals[0].slot)).toBe(false);
  });
});

describe("AddToPlan", () => {
  const open = async () => {
    fireEvent.click(await screen.findByRole("button", { name: "Add to my plan" }));
    return screen.getByLabelText("When?");
  };

  it("swaps the recipe into the chosen meal", async () => {
    const calls = mockApi({
      "GET /plans/current": json(makePlan({ start: today })),
      "POST /plans/replan": json({
        type: "outcome",
        results: [{ status: "applied", message: "Today's lunch is now Soup." }],
      }),
    });
    renderWithClient(<AddToPlan recipe={OTHER} />);

    await open();
    fireEvent.click(screen.getByRole("button", { name: "Add to my plan" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Today's lunch is now Soup."));
    const body = calls.find((c) => c.path === "/plans/replan")?.body as {
      changes: { intent: string; recipe_id: number; when: { date: string } }[];
    };
    expect(body.changes[0]).toMatchObject({
      intent: "swap",
      recipe_id: 999,
      when: { date: today },
    });
    expect(screen.queryByLabelText("When?")).not.toBeInTheDocument();
  });

  it("says why when the plan refuses it, and stays open", async () => {
    mockApi({
      "GET /plans/current": json(makePlan({ start: today })),
      "POST /plans/replan": json({
        type: "outcome",
        results: [{ status: "failed", message: "That has peanuts in it." }],
      }),
    });
    renderWithClient(<AddToPlan recipe={OTHER} />);

    await open();
    fireEvent.click(screen.getByRole("button", { name: "Add to my plan" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("That has peanuts in it."));
    expect(screen.getByLabelText("When?")).toBeInTheDocument();
  });

  it("shows nothing without a plan", async () => {
    const calls = mockApi({ "GET /plans/current": json(null) });
    const { container } = renderWithClient(<AddToPlan recipe={OTHER} />);

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(container).toBeEmptyDOMElement();
  });
});
