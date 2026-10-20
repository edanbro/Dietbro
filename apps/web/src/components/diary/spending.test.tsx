import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Spending } from "@/lib/api/hooks";
import { json, mockApi, renderWithClient } from "@/test/api";

import { SpendingSection } from "./spending";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

afterEach(() => vi.unstubAllGlobals());

const week = (start: string, spent: number, planned: number | null = null) => ({
  start,
  spent_minor: spent,
  planned_minor: planned,
});

describe("SpendingSection", () => {
  it("summarises weekly spend and the aisles it went on", async () => {
    const data: Spending = {
      currency: "EUR",
      weeks: [week("2026-09-28", 0), week("2026-10-05", 6000, 5500), week("2026-10-12", 4000)],
      categories: [
        { category: "Beef Products", spent_minor: 3000 },
        { category: "Poultry Products", spent_minor: 2000 },
        { category: "Vegetables and Vegetable Products", spent_minor: 4000 },
      ],
      unmatched_minor: 1000,
    };
    mockApi({ "GET /insights/spending": json(data) });
    renderWithClient(<SpendingSection />);

    expect(
      await screen.findByRole("img", { name: "About €50.00 a week on groceries, over 2 weeks with receipts." }),
    ).toBeInTheDocument();
    const aisles = screen.getByRole("list", { name: "Most spent on" });
    // Beef and poultry are both the meat aisle: €50 before vegetables' €40.
    expect(aisles.firstElementChild).toHaveTextContent("Meat€50.00");
    expect(aisles.lastElementChild).toHaveTextContent("Vegetables€40.00");
  });

  it("points to receipts when there are none", async () => {
    mockApi({
      "GET /insights/spending": json({
        currency: "EUR",
        weeks: [week("2026-10-12", 0)],
        categories: [],
        unmatched_minor: 0,
      }),
    });
    renderWithClient(<SpendingSection />);
    expect(await screen.findByRole("link", { name: "Add a receipt" })).toHaveAttribute(
      "href",
      "/pantry/receipts",
    );
  });
});
