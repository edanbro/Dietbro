import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Prices } from "@/lib/api/hooks";
import { json, mockApi, renderWithClient } from "@/test/api";

import { PriceWatch } from "./price-watch";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

afterEach(() => vi.unstubAllGlobals());

const PRICES: Prices = {
  currency: "EUR",
  items: [
    {
      food_id: 1,
      name: "Chicken, broilers or fryers, breast, skinless, boneless, meat only, raw",
      history: [
        { on: "2026-09-01", per_kg_minor: 900 },
        { on: "2026-09-20", per_kg_minor: 920 },
        { on: "2026-10-10", per_kg_minor: 1080 },
      ],
      latest_minor: 1080,
      usual_minor: 910,
      change_pct: 19,
      rise: true,
      cheaper: { label: "Lidl chicken fillets", per_kg_minor: 790, last_bought: "2026-09-12" },
    },
    {
      food_id: 2,
      name: "Rice, white, long-grain, regular, raw",
      history: [
        { on: "2026-09-01", per_kg_minor: 200 },
        { on: "2026-10-01", per_kg_minor: 180 },
      ],
      latest_minor: 180,
      usual_minor: 200,
      change_pct: -10,
      rise: false,
      cheaper: null,
    },
  ],
};

describe("PriceWatch", () => {
  it("lists rises first with a cheaper option, in friendly names", async () => {
    mockApi({ "GET /insights/prices": json(PRICES) });
    renderWithClient(<PriceWatch />);

    const rows = within(
      await screen.findByRole("list", { name: "Prices you've paid" }),
    ).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Chicken · breast");
    expect(rows[0]).toHaveTextContent("€10.80/kg, usually €9.10");
    expect(rows[0]).toHaveTextContent("+19%");
    expect(rows[0]).toHaveTextContent("Cheaper: Lidl chicken fillets at €7.90/kg");
    expect(rows[1]).toHaveTextContent("-10%");
    expect(rows[1]).not.toHaveTextContent("Cheaper");
  });

  it("explains what it needs when there's nothing yet", async () => {
    mockApi({ "GET /insights/prices": json({ currency: "EUR", items: [] }) });
    renderWithClient(<PriceWatch />);
    expect(await screen.findByText(/bought something twice/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add a receipt" })).toHaveAttribute(
      "href",
      "/pantry/receipts",
    );
  });
});
