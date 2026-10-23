import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";

import { QuickNightsForm } from "./quick-nights-form";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

afterEach(() => vi.unstubAllGlobals());

const PREFS = {
  diet: null,
  liked_cuisines: [],
  disliked_cuisines: [],
  liked_food_ids: [],
  disliked_food_ids: [],
  liked_foods: [],
  disliked_foods: [],
  quick_days: [0],
  quick_minutes: 30,
};

describe("QuickNightsForm", () => {
  it("shows the saved nights and saves new ones", async () => {
    const sent: unknown[] = [];
    mockApi({
      "GET /me/preferences": json(PREFS),
      "PUT /me/preferences/quick-nights": async (req: Request) => {
        sent.push(await req.json());
        return Response.json({ ...PREFS, quick_days: [0, 2], quick_minutes: 20 });
      },
    });
    renderWithClient(<QuickNightsForm />);

    const monday = await screen.findByRole("button", { name: "Monday" });
    expect(monday).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Wednesday" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    const save = screen.getByRole("button", { name: "Save busy nights" });
    expect(save).toBeDisabled(); // nothing changed yet

    fireEvent.click(screen.getByRole("button", { name: "Wednesday" }));
    fireEvent.change(screen.getByLabelText("At most"), { target: { value: "20" } });
    fireEvent.click(save);

    await waitFor(() => expect(sent).toEqual([{ days: [0, 2], minutes: 20 }]));
  });

  it("asks for preferences first", async () => {
    mockApi({ "GET /me/preferences": json(null) });
    renderWithClient(<QuickNightsForm />);
    expect(await screen.findByText(/Set your preferences first/)).toBeInTheDocument();
  });
});
