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
    expect(screen.getByRole("radio", { name: "I'll sort it", checked: true })).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save meals" });
    expect(save).toBeDisabled();
    fireEvent.click(screen.getAllByRole("radio", { name: "Skip it" })[0]!); // breakfast
    fireEvent.click(screen.getByRole("radio", { name: "Never" }));
    fireEvent.click(save);

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      breakfast: "skip",
      lunch: "own",
      dinner: "plan",
      snack: "skip",
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
