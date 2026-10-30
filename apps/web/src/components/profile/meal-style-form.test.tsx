import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { json, mockApi, renderWithClient } from "@/test/api";

import { MealStyleForm } from "./meal-style-form";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

const PREFS = {
  diet: null,
  liked_cuisines: [],
  disliked_cuisines: [],
  liked_food_ids: [],
  disliked_food_ids: [],
  meals: { breakfast: "plan", lunch: "plan", dinner: "plan", snack: "plan" },
  meal_style: "everyday",
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("MealStyleForm", () => {
  it("shows the saved style and saves a new one as soon as it's picked", async () => {
    const calls = mockApi({
      "GET /me/preferences": json(PREFS),
      "PUT /me/preferences/meal-style": json({ ...PREFS, meal_style: "mix" }),
    });
    renderWithClient(<MealStyleForm />);

    expect(await screen.findByRole("radio", { name: /Familiar meals/ })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: /A mix/ }));

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ meal_style: "mix" });
  });

  it("shows nothing until preferences are set", async () => {
    const calls = mockApi({ "GET /me/preferences": json(null) });
    const { container } = renderWithClient(<MealStyleForm />);

    await waitFor(() => expect(calls).toHaveLength(1));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
