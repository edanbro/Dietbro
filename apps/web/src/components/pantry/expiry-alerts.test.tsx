import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { localISODate } from "@/lib/dates";
import { json, mockApi, renderWithClient } from "@/test/api";
import { MILK, TOMATOES } from "@/test/fixtures";

import { ExpiryAlerts, expiryText } from "./expiry-alerts";

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

afterEach(() => vi.unstubAllGlobals());

const item = (id: number, food: typeof MILK, days_left: number) => ({
  id,
  food,
  grams: 500,
  quantity: 500,
  unit: "g",
  approx: false,
  expires_on: "2026-10-10",
  source: "receipt",
  created_at: "2026-10-01T09:00:00Z",
  days_left,
});

describe("expiryText", () => {
  it.each([
    [-3, "expired 3 days ago"],
    [-1, "expired yesterday"],
    [0, "use today"],
    [1, "expires tomorrow"],
    [2, "expires in 2 days"],
  ])("%i -> %s", (days, text) => expect(expiryText(days)).toBe(text));
});

describe("ExpiryAlerts", () => {
  it("lists expired and soon-expiring food for the local today", async () => {
    const calls = mockApi({
      "GET /pantry/expiring": json({
        today: "2026-10-11",
        days: 3,
        expired: 1,
        items: [item(1, MILK, -2), item(2, TOMATOES, 1)],
      }),
    });
    renderWithClient(<ExpiryAlerts />);

    const region = await screen.findByRole("region", { name: "Use soon" });
    expect(region).toHaveTextContent("1 expired, 1 to use in the next 3 days");
    const rows = within(region).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      `${MILK.description}expired 2 days ago`,
      `${TOMATOES.description}expires tomorrow`,
    ]);
    const url = new URL(`http://x${calls[0].path}`);
    expect(url.pathname).toBe("/pantry/expiring");
  });

  it("asks for the user's local date", async () => {
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (req: Request) => {
        urls.push(req.url);
        return Response.json({ today: "2026-10-11", days: 3, expired: 0, items: [] });
      }),
    );
    const { container } = renderWithClient(<ExpiryAlerts />);

    await vi.waitFor(() => expect(urls).toHaveLength(1));
    const query = new URL(urls[0]).searchParams;
    expect(query.get("today")).toBe(localISODate());
    expect(query.get("days")).toBe("3");
    expect(container).toBeEmptyDOMElement();
  });
});
