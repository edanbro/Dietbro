import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";

import { MealsForm } from "./meals-form";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "test-token" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

const PREFS = {
  diet: null,
  liked_cuisines: [],
  disliked_cuisines: [],
  liked_food_ids: [],
  disliked_food_ids: [],
  meals: { breakfast: "plan", lunch: "own", dinner: "plan", snack: "plan" },
};

afterEach(() => vi.unstubAllGlobals());

describe("MealsForm", () => {
  it("shows the saved choices and saves a change", async () => {
    const calls = mockApi({
      "GET /me/preferences": json(PREFS),
      "PUT /me/preferences/meals": json(PREFS),
    });
    renderWithClient(<MealsForm />);

    await screen.findByRole("group", { name: "Lunch" });
    expect(screen.getAllByRole("radio", { name: "I'll sort it", checked: true })).toHaveLength(1);
    expect(screen.getByRole("group", { name: "Morning snack" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Afternoon snack" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Evening snack" })).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save meals" });
    expect(save).toBeDisabled();
    fireEvent.click(screen.getAllByRole("radio", { name: "Skip it" })[0]!); // breakfast
    fireEvent.click(screen.getAllByRole("radio", { name: "Plan it" })[3]!); // morning snack
    fireEvent.click(screen.getAllByRole("radio", { name: "I'll sort it" })[5]!); // evening snack
    fireEvent.click(save);

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      breakfast: "skip",
      morning_snack: "plan",
      lunch: "own",
      snack: "plan",
      dinner: "plan",
      evening_snack: "own",
    });
  });

  it("shows why a choice can't be planned", async () => {
    mockApi({
      "GET /me/preferences": json(PREFS),
      "PUT /me/preferences/meals": json(
        { detail: ["Plan at least one of breakfast, lunch and dinner."] },
        400,
      ),
    });
    renderWithClient(<MealsForm />);

    fireEvent.click((await screen.findAllByRole("radio", { name: "I'll sort it" }))[2]!); // dinner
    fireEvent.click(screen.getAllByRole("radio", { name: "I'll sort it" })[0]!); // breakfast
    fireEvent.click(screen.getByRole("button", { name: "Save meals" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Plan at least one");
  });
});
