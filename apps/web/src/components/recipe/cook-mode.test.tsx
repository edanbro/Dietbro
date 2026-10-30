import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Recipe } from "@/lib/api/hooks";
import { localISODate } from "@/lib/dates";
import { json, mockApi, renderWithClient } from "@/test/api";
import { makePlan, makeRecipe } from "@/test/fixtures";
import { resetNavigation } from "@/test/navigation";

import { CookMode } from "./cook-mode";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const RECIPE: Recipe = {
  id: 5,
  name: "Irish stew",
  category: "Lamb",
  cuisine: "Irish",
  image_url: null,
  instructions: "Brown the lamb.\nSimmer for 90 minutes.\nServe.",
  generated: false,
  source: "curated",
  source_url: null,
  servings: 4,
  servings_estimated: false,
  per_serving: null,
  grade: null,
  meal_types: ["dinner"],
  allergens: [],
  allergens_complete: true,
  suitable_for: [],
  ingredients: [
    {
      name: "lamb neck",
      measure: "800 g",
      food_id: 1,
      food_name: "Lamb",
      grams: 800,
      in_pantry: false,
    },
    {
      name: "potatoes",
      measure: "1 kg",
      food_id: 2,
      food_name: "Potatoes",
      grams: 1000,
      in_pantry: true,
    },
    {
      name: "salt",
      measure: "to taste",
      food_id: null,
      food_name: null,
      grams: null,
      in_pantry: false,
    },
  ],
  feedback: null,
};

beforeEach(() => mockApi({ "GET /recipes/5": json(RECIPE) }));
afterEach(() => vi.unstubAllGlobals());

describe("CookMode", () => {
  it("scales to the planned servings and marks what's in the pantry", async () => {
    resetNavigation("/recipes/5/cook?servings=2");
    renderWithClient(<CookMode id={5} />);

    const list = within(await screen.findByRole("region", { name: "Ingredients" }));
    expect(screen.getByText("2 servings")).toBeInTheDocument();
    const rows = list.getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("400 g");
    expect(rows[1]).toHaveTextContent("500 g");
    expect(rows[1]).toHaveTextContent("In your pantry");
    expect(rows[2]).toHaveTextContent("to taste");

    fireEvent.click(screen.getByRole("button", { name: "More servings" }));
    expect(screen.getByText("2.5 servings")).toBeInTheDocument();
    expect(rows[0]).toHaveTextContent("500 g");
  });

  it("shows the recipe's own amounts without ?servings", async () => {
    resetNavigation("/recipes/5/cook");
    renderWithClient(<CookMode id={5} />);
    expect(await screen.findByText("4 servings")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("800 g");
  });

  it("ticks off steps and offers timers", async () => {
    resetNavigation("/recipes/5/cook");
    renderWithClient(<CookMode id={5} />);

    expect(await screen.findByLabelText("90 minutes timer")).toHaveTextContent("1:30:00");
    const steps = screen.getAllByRole("button", { name: /^Step \d done$/ });
    expect(steps).toHaveLength(3);
    steps.forEach((s) => fireEvent.click(s));
    expect(screen.getByRole("status")).toHaveTextContent("All done");
    expect(screen.queryByLabelText("90 minutes timer")).not.toBeInTheDocument();
  });
});

describe("finishing", () => {
  it("offers to mark today's planned meal eaten once every step is done", async () => {
    const recipe = makeRecipe({ instructions: "Boil it." });
    const today = localISODate();
    const plan = makePlan({ start: today });
    plan.days[0].meals[1].recipe = { ...plan.days[0].meals[1].recipe, id: recipe.id };
    const calls = mockApi({
      [`GET /recipes/${recipe.id}`]: json(recipe),
      "GET /plans/current": json(plan),
      [`POST /plans/${plan.id}/meals/eaten`]: json({ applied: true }),
    });
    renderWithClient(<CookMode id={recipe.id} />);

    fireEvent.click(await screen.findByRole("button", { name: "Step 1 done" }));
    fireEvent.click(await screen.findByRole("button", { name: "Mark lunch eaten" }));

    await waitFor(() => {
      const sent = calls.find((c) => c.path === `/plans/${plan.id}/meals/eaten`);
      expect(sent?.body).toMatchObject({ date: today, slot: "lunch" });
    });
  });
});
