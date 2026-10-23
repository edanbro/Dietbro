import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PrepPicker, prepChoices } from "@/components/plan/prep-picker";
import type { Recipe } from "@/lib/api/hooks";
import { json, mockApi, renderWithClient } from "@/test/api";
import { makePlan, makeRecipe } from "@/test/fixtures";
import { calls as nav, resetNavigation } from "@/test/navigation";

import { gatherIngredients, MealPrep, offset } from "./meal-prep";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

beforeEach(() => resetNavigation("/prep"));
afterEach(() => vi.unstubAllGlobals());

const ing = (name: string, food_id: number | null, grams: number | null, measure = "") => ({
  name,
  measure,
  food_id,
  food_name: null,
  grams,
  in_pantry: false,
});

const CHILLI: Recipe = makeRecipe({
  id: 1,
  name: "Chilli",
  servings: 4,
  instructions: "Brown the mince for 5 minutes.\nSimmer for 40 minutes.\nSeason.",
  ingredients: [
    ing("Mince", 10, 500),
    ing("Onion", 20, 200),
    ing("Chilli flakes", null, null, "a pinch"),
  ],
});
const RICE: Recipe = makeRecipe({
  id: 2,
  name: "Rice",
  servings: 2,
  instructions: "Boil the rice for 12 minutes.\nDrain.",
  ingredients: [ing("Rice", 30, 150), ing("Onion", 20, 100)],
});

describe("gatherIngredients", () => {
  it("adds up the same food across recipes, scaled to the servings", () => {
    const lines = gatherIngredients([
      { recipe: CHILLI, servings: 8 },
      { recipe: RICE, servings: 2 },
    ]);
    const onion = lines.find((l) => l.name === "Onion")!;
    expect(onion.amount).toBe("500 g"); // 200 g x2 + 100 g
    expect(onion.recipes).toEqual(["Chilli", "Rice"]);
    expect(lines.find((l) => l.name === "Mince")!.amount).toBe("1 kg");
    expect(lines.find((l) => l.name === "Chilli flakes")!.amount).toBe("a pinch");
  });
});

describe("offset", () => {
  it.each([
    [0, "Start"],
    [300, "5 min"],
    [3600, "1 h"],
    [3900, "1 h 5 min"],
  ])("%i -> %s", (s, text) => expect(offset(s)).toBe(text));
});

describe("MealPrep", () => {
  it("interleaves the recipes into one timeline", async () => {
    resetNavigation("/prep?r=1x8,2x2");
    mockApi({ "GET /recipes/1": json(CHILLI), "GET /recipes/2": json(RICE) });
    renderWithClient(<MealPrep />);

    expect(await screen.findByRole("heading", { name: "Meal prep" })).toBeInTheDocument();
    const cooking = within(screen.getByRole("list", { name: "Cooking" }));
    expect(cooking.getByText("Chilli · 8 servings")).toBeInTheDocument();
    const steps = within(screen.getByRole("region", { name: "Steps" })).getAllByRole("listitem");
    expect(steps[0]).toHaveTextContent("Chilli · step 1");
    expect(steps[0]).toHaveAttribute("aria-current", "step");
    // The rice is cooked while the chilli simmers, not after it.
    const simmer = steps.findIndex((s) => s.textContent?.includes("Simmer"));
    const boil = steps.findIndex((s) => s.textContent?.includes("Boil the rice"));
    expect(boil).toBe(simmer + 1);

    fireEvent.click(screen.getByRole("button", { name: "Chilli step 1 done" }));
    expect(steps[0]).not.toHaveAttribute("aria-current");
  });

  it("points back to the plan without recipes", () => {
    renderWithClient(<MealPrep />);
    expect(screen.getByText("Nothing to prep")).toBeInTheDocument();
  });
});

describe("PrepPicker", () => {
  it("adds up servings per recipe and opens meal prep with the chosen ones", () => {
    const plan = makePlan();
    const today = plan.days[0]!.date;
    const choices = prepChoices(plan, today);
    const first = choices[0]!;
    expect(first.meals).toBeGreaterThanOrEqual(1);

    renderWithClient(<PrepPicker plan={plan} today={today} />);
    fireEvent.click(screen.getByRole("button", { name: "Meal prep" }));
    fireEvent.click(screen.getByRole("checkbox", { name: new RegExp(`^${first.name}`) }));
    fireEvent.click(screen.getByRole("button", { name: "Start meal prep" }));
    expect(nav.push.at(-1)).toBe(`/prep?r=${first.id}x${first.servings}`);
  });

  it("cooks for everyone when the plan is for a household", () => {
    const plan = makePlan();
    const today = plan.days[0]!.date;
    const alone = prepChoices(plan, today);
    const family = prepChoices({ ...plan, household: 3 }, today);

    expect(family.map((c) => c.servings)).toEqual(alone.map((c) => c.servings * 3));
  });
});
