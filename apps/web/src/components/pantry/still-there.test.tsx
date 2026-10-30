import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PantryItem } from "@/lib/api/hooks";
import { addDays, localISODate } from "@/lib/dates";
import { json, mockApi, renderWithClient } from "@/test/api";
import { MILK, TOMATOES } from "@/test/fixtures";

import { StillThere, staleItems } from "./still-there";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

afterEach(() => vi.unstubAllGlobals());

const TODAY = "2026-10-30";

const item = (id: number, overrides: Partial<PantryItem>): PantryItem => ({
  id,
  food: MILK,
  grams: 500,
  quantity: 500,
  unit: "g",
  approx: false,
  expires_on: null,
  source: "manual",
  created_at: "2026-01-01T09:00:00Z",
  storage: "fridge",
  checked_on: "2026-01-01",
  ...overrides,
});

describe("staleItems", () => {
  it("waits longer for the cupboard and the freezer than the fridge", () => {
    const at = (days: number) => addDays(TODAY, -days);
    const items = [
      item(1, { storage: "fridge", checked_on: at(7) }),
      item(2, { storage: "fridge", checked_on: at(8) }),
      item(3, { storage: "cupboard", checked_on: at(30) }),
      item(4, { storage: "cupboard", checked_on: at(31) }),
      item(5, { storage: "freezer", checked_on: at(60) }),
      item(6, { storage: "freezer", checked_on: at(61) }),
    ];

    expect(staleItems(items, TODAY).map((i) => i.id)).toEqual([6, 4, 2]);
  });

  it("leaves food the expiry alert already covers, but asks about far-off dates", () => {
    const items = [
      item(1, { expires_on: addDays(TODAY, 2) }),
      item(2, { expires_on: addDays(TODAY, -5) }),
      item(3, { expires_on: addDays(TODAY, 3) }),
    ];

    expect(staleItems(items, TODAY).map((i) => i.id)).toEqual([3]);
  });

  it("asks about five at most, the oldest check first", () => {
    const items = [6, 5, 4, 3, 2, 1].map((n) => item(n, { checked_on: addDays(TODAY, -100 + n) }));

    expect(staleItems(items, TODAY).map((i) => i.id)).toEqual([1, 2, 3, 4, 5]);
  });

  it("doesn't ask about a response without a date (a cache from an older version)", () => {
    const old = { ...item(1, {}), checked_on: undefined } as unknown as PantryItem;

    expect(staleItems([old], TODAY)).toEqual([]);
  });
});

describe("StillThere", () => {
  const stale = addDays(localISODate(), -40);

  it("confirms an item, or removes it when it's used up", async () => {
    const calls = mockApi({
      "GET /pantry": json([
        item(1, { checked_on: stale }),
        item(2, { food: TOMATOES, checked_on: stale }),
      ]),
      "POST /pantry/1/confirm": json(item(1, {})),
      "DELETE /pantry/2": () => new Response(null, { status: 204 }),
    });
    const sent = () => calls.map((c) => `${c.method} ${c.path}`);
    renderWithClient(<StillThere />);

    const region = await screen.findByRole("region", { name: "Still in your kitchen?" });
    fireEvent.click(within(region).getByRole("button", { name: /^Milk.*still here$/ }));
    await vi.waitFor(() => expect(sent()).toContain("POST /pantry/1/confirm"));
    const usedUp = within(region).getByRole("button", { name: /tomatoes: used up$/i });
    await vi.waitFor(() => expect(usedUp).toBeEnabled());
    fireEvent.click(usedUp);
    await vi.waitFor(() => expect(sent()).toContain("DELETE /pantry/2"));
  });

  it("shows nothing when everything was checked lately", async () => {
    const calls = mockApi({ "GET /pantry": json([item(1, { checked_on: localISODate() })]) });
    const { container } = renderWithClient(<StillThere />);

    await vi.waitFor(() => expect(calls).toHaveLength(1));
    expect(container).toBeEmptyDOMElement();
  });
});
