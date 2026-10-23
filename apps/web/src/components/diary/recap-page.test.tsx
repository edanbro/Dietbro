import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Recap } from "@/lib/api/hooks";
import { json, mockApi, renderWithClient } from "@/test/api";
import { calls as nav, resetNavigation } from "@/test/navigation";

import { RecapPage } from "./recap-page";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));

beforeEach(() => resetNavigation("/recap"));
afterEach(() => vi.unstubAllGlobals());

const RECAP: Recap = {
  week_start: "2026-10-12",
  week_end: "2026-10-18",
  currency: "EUR",
  planned_meals: 21,
  eaten_meals: 15,
  skipped_meals: 1,
  off_plan: 2,
  logged_days: 6,
  avg_kcal: 2050,
  kcal_min: 1800,
  kcal_max: 2300,
  on_target_days: 5,
  protein_g_min: 90,
  protein_days: 4,
  spent_minor: 6240,
  budget_minor: 7000,
  planned_cost_minor: 6685,
  weight_change_kg: -0.6,
  weight_kg: 79.4,
  top_recipes: [
    {
      recipe: { id: 5, name: "Irish stew", category: null, cuisine: null, image_url: null },
      times: 3,
    },
  ],
  price_rises: [{ name: "Butter, salted", change_pct: 18 }],
  empty: false,
};

describe("RecapPage", () => {
  it("looks back on the week", async () => {
    const calls = mockApi({ "GET /insights/recap": json(RECAP) });
    renderWithClient(<RecapPage />);

    const meals = within(await screen.findByRole("region", { name: "Meals" }));
    expect(meals.getByText("15 of 21")).toBeInTheDocument();
    expect(meals.getByText(/1 skipped · 2 off the plan/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Calories" })).toHaveTextContent(
      "5 of 6 days logged within 1,800–2,300 kcal",
    );
    expect(screen.getByRole("region", { name: "Spending" })).toHaveTextContent(
      "€62.40of a €70.00 budget; the plan expected €66.85",
    );
    expect(screen.getByRole("region", { name: "Weight" })).toHaveTextContent("-0.6 kg");
    expect(screen.getByRole("link", { name: "Irish stew" })).toHaveAttribute("href", "/recipes/5");
    expect(screen.getByRole("region", { name: "Prices up" })).toHaveTextContent("Salted butter+18%");
    expect(calls[0]?.path).toBe("/insights/recap");

    fireEvent.click(screen.getByRole("button", { name: "Week before" }));
    expect(nav.replace.at(-1)).toBe("/recap?week=2026-10-05");
  });

  it("says when there's nothing for that week", async () => {
    resetNavigation("/recap?week=2026-10-05");
    mockApi({
      "GET /insights/recap": json({
        ...RECAP,
        week_start: "2026-10-05",
        week_end: "2026-10-11",
        empty: true,
      }),
    });
    renderWithClient(<RecapPage />);
    expect(await screen.findByText("Nothing that week")).toBeInTheDocument();
  });
});
