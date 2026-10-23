import { fireEvent, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";
import { makeRecipe } from "@/test/fixtures";
import { calls as nav, resetNavigation } from "@/test/navigation";

import { CookMode } from "./cook-mode";
import { draftOf, RecipeEdit } from "./recipe-edit";
import { RecipeNotes } from "./recipe-notes";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() } }));

beforeEach(() => {
  resetNavigation("/recipes/101/edit");
  vi.mocked(toast.success).mockClear();
});
afterEach(() => vi.unstubAllGlobals());

describe("draftOf", () => {
  it("turns a recipe into the form's draft", () => {
    const draft = draftOf(makeRecipe({ meal_types: ["breakfast", "lunch"], servings: 12 }));
    expect(draft.slot).toBe("lunch"); // the main meal it suits
    expect(draft.servings).toBe(8); // the form's most
    expect(draft.ingredients[0]).toEqual({ line: "", name: "Onion", quantity: "1 large" });
  });
});

describe("RecipeEdit", () => {
  it("saves a catalogue recipe as the user's copy and opens it", async () => {
    const calls = mockApi({
      "GET /recipes/101": json(makeRecipe()),
      "PUT /recipes/101": json({ recipe_id: 555, problems: [], copied: true }),
    });
    renderWithClient(<RecipeEdit id={101} />);

    expect(await screen.findByText(/saves your own copy/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "My shakshuka" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(nav.push.at(-1)).toBe("/recipes/555"));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.body).toMatchObject({ name: "My shakshuka", slot: "lunch" });
    expect(toast.success).toHaveBeenCalledWith("Saved My shakshuka to your recipes");
  });

  it("shows what to fix when the change isn't safe", async () => {
    mockApi({
      "GET /recipes/101": json(makeRecipe({ generated: true })),
      "PUT /recipes/101": json({
        recipe_id: null,
        problems: ["it contains peanuts, which you're allergic to"],
        copied: false,
      }),
    });
    renderWithClient(<RecipeEdit id={101} />);

    expect(await screen.findByText(/changes for every plan from now on/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText(/which you're allergic to/)).toBeInTheDocument();
    expect(nav.push).toEqual([]);
  });
});

describe("RecipeNotes", () => {
  it("rates and offers favourites for five stars", async () => {
    const calls = mockApi({
      "PUT /recipes/101/note": json({ note: null, rating: 5, updated_at: "2026-10-23T12:00:00Z" }),
    });
    renderWithClient(<RecipeNotes recipe={makeRecipe()} />);

    fireEvent.click(screen.getByRole("radio", { name: "5 stars" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ note: null, rating: 5 });
    expect(vi.mocked(toast.success).mock.calls[0]![1]).toMatchObject({
      action: { label: "Add to favourites" },
    });
  });

  it("saves a note", async () => {
    const calls = mockApi({
      "PUT /recipes/101/note": json({
        note: "More chilli",
        rating: 4,
        updated_at: "2026-10-23T12:00:00Z",
      }),
    });
    renderWithClient(
      <RecipeNotes
        recipe={makeRecipe({ note: { note: null, rating: 4, updated_at: "2026-10-22T12:00:00Z" } })}
      />,
    );

    expect(screen.getByRole("radio", { name: "4 stars" })).toHaveAttribute("aria-checked", "true");
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: " More chilli " } });
    fireEvent.click(screen.getByRole("button", { name: "Save note" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Note saved"));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ note: "More chilli", rating: 4 });
  });
});

describe("CookMode", () => {
  it("pins the user's note at the top", async () => {
    resetNavigation("/recipes/101/cook");
    mockApi({
      "GET /recipes/101": json(
        makeRecipe({
          note: { note: "Less salt", rating: null, updated_at: "2026-10-22T12:00:00Z" },
        }),
      ),
    });
    renderWithClient(<CookMode id={101} />);
    expect(await screen.findByRole("note")).toHaveTextContent("Your note: Less salt");
  });
});
