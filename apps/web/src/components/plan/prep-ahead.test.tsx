import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";

import { PrepAhead } from "./prep-ahead";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));

afterEach(() => vi.unstubAllGlobals());

describe("PrepAhead", () => {
  it("lists what to defrost and what to start tonight", async () => {
    mockApi({
      "GET /plans/ahead": json({
        date: "2026-10-15",
        items: [
          {
            kind: "defrost",
            slot: "dinner",
            recipe_id: 7,
            recipe_name: "Chicken curry",
            text: "Chicken, broilers or fryers, breast, meat only, raw",
          },
          {
            kind: "start",
            slot: "lunch",
            recipe_id: 9,
            recipe_name: "Shawarma",
            text: "Marinate overnight.",
          },
        ],
      }),
    });
    renderWithClient(<PrepAhead />);

    const card = await screen.findByRole("region", { name: "Tonight, for tomorrow" });
    const [defrost, start] = card.querySelectorAll("li");
    expect(defrost).toHaveTextContent("Take the chicken out of the freezer");
    expect(defrost).toHaveTextContent("For Chicken curry (dinner)");
    expect(start).toHaveTextContent("Marinate overnight.");
    expect(screen.getByRole("link", { name: "Shawarma" })).toHaveAttribute("href", "/recipes/9");
  });

  it("shows nothing when there's nothing to do", async () => {
    const calls = mockApi({ "GET /plans/ahead": json({ date: "2026-10-15", items: [] }) });
    const { container } = renderWithClient(<PrepAhead />);
    await vi.waitFor(() => expect(calls.length).toBe(1));
    expect(container).toBeEmptyDOMElement();
  });
});
