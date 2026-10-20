import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";
import { calls as nav, resetNavigation } from "@/test/navigation";

import { RecipeImport } from "./recipe-import";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

beforeEach(() => resetNavigation("/recipes/import"));
afterEach(() => vi.unstubAllGlobals());

const DRAFT = {
  name: "Chicken and rice",
  slot: "dinner",
  servings: 2,
  cuisine: null,
  ingredients: [
    { line: "300g chicken breast, diced", name: "chicken breast", quantity: "300g" },
    { line: "150 g rice", name: "rice", quantity: "150 g" },
  ],
  instructions: "Cook the rice.",
  image_url: null,
  source_url: "https://example.com/recipe",
};

async function readLink() {
  fireEvent.change(screen.getByLabelText("Recipe link"), {
    target: { value: "https://example.com/recipe" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Read" }));
  return screen.findByRole("form", { name: "Recipe to save" });
}

describe("RecipeImport", () => {
  it("reads a link into a draft, then saves it and opens the recipe", async () => {
    const calls = mockApi({
      "POST /recipes/import/read": json(DRAFT),
      "POST /recipes/import": json({ recipe_id: 42, problems: [] }),
    });
    renderWithClient(<RecipeImport />);

    await readLink();
    expect(screen.getByLabelText("Name")).toHaveValue("Chicken and rice");
    expect(screen.getByLabelText("Ingredient 1")).toHaveValue("chicken breast");
    expect(screen.getByText("From the page: 300g chicken breast, diced")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Ingredient 2"), { target: { value: "basmati rice" } });
    fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));

    await waitFor(() => expect(nav.push).toEqual(["/recipes/42"]));
    const sent = calls.find((c) => c.path === "/recipes/import")!.body as typeof DRAFT;
    expect(sent.ingredients.map((i) => i.name)).toEqual(["chicken breast", "basmati rice"]);
    expect(sent.source_url).toBe("https://example.com/recipe");
  });

  it("shows what to fix when the recipe can't be saved", async () => {
    mockApi({
      "POST /recipes/import/read": json(DRAFT),
      "POST /recipes/import": json({
        recipe_id: null,
        problems: ["couldn't match 'zorblax' - use a common ingredient name"],
      }),
    });
    renderWithClient(<RecipeImport />);

    await readLink();
    fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't match 'zorblax'");
    expect(nav.push).toEqual([]);
  });

  it("says why a link can't be read, and allows typing the recipe in", async () => {
    mockApi({
      "POST /recipes/import/read": json(
        { detail: "No recipe found on that page. Paste the ingredients and method instead." },
        422,
      ),
    });
    renderWithClient(<RecipeImport />);

    fireEvent.change(screen.getByLabelText("Recipe link"), {
      target: { value: "https://example.com/blog" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Read" }));
    expect(await screen.findByText(/No recipe found on that page/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Type a recipe in instead" }));
    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getAllByLabelText(/^Ingredient \d/)).toHaveLength(2);
  });
});
