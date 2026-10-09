import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { json, mockApi, renderWithClient } from "@/test/api";
import { makeRecipe } from "@/test/fixtures";
import { calls as nav, resetNavigation } from "@/test/navigation";

import { RecipePage, safeUrl, steps } from "./recipe-page";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => null }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));

const ALLERGENS = [
  { code: "eggs", label: "Eggs" },
  { code: "milk", label: "Milk" },
];

beforeEach(() => resetNavigation("/recipes/101"));
afterEach(() => vi.unstubAllGlobals());

describe("helpers", () => {
  it("keeps only http(s) links", () => {
    expect(safeUrl("https://example.com/a")?.hostname).toBe("example.com");
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("not a url")).toBeNull();
    expect(safeUrl(null)).toBeNull();
  });

  it("splits instructions into steps", () => {
    expect(steps("One.\r\n\r\nTwo.\nThree. ")).toEqual(["One.", "Two.", "Three."]);
  });
});

describe("RecipePage", () => {
  it("shows the recipe: photo, numbers, allergens, diets, ingredients, method and credit", async () => {
    mockApi({ "GET /recipes/101": json(makeRecipe()), "GET /allergens": json(ALLERGENS) });
    renderWithClient(<RecipePage id={101} />);

    expect(await screen.findByRole("heading", { level: 1, name: "Shakshuka" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Shakshuka" })).toHaveAttribute(
      "src",
      "https://img.example/shakshuka.jpg",
    );
    expect(screen.getByText("Egyptian · Serves 4 (estimated)")).toBeInTheDocument();
    // MealDB's category ("Vegetarian") is not a diet claim and isn't shown as one.
    // Only the derived diet badge says "Vegetarian".
    expect(screen.getAllByText(/Vegetarian/)).toHaveLength(1);

    const nutrition = screen.getByRole("region", { name: "Per serving" });
    expect(nutrition).toHaveTextContent("320 kcal");
    expect(nutrition).toHaveTextContent("18 g");

    const allergens = screen.getByRole("region", { name: "Allergens" });
    expect(
      within(within(allergens).getByRole("list", { name: "Contains" }))
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["Eggs", "Milk"]);
    expect(allergens).toHaveTextContent("May be incomplete");
    expect(allergens).toHaveTextContent("Suitable for:Vegetarian");

    const ingredients = within(screen.getByRole("region", { name: "Ingredients" })).getAllByRole(
      "listitem",
    );
    expect(ingredients.map((li) => li.textContent)).toEqual(["1 largeOnion", "4Eggs", "Feta"]);

    const method = screen.getByRole("region", { name: "Method" });
    expect([...method.querySelectorAll("p")].map((p) => p.textContent)).toEqual([
      "Fry the onion.",
      "Add the tomatoes and simmer.",
      "Crack in the eggs.",
    ]);

    expect(screen.getByRole("link", { name: "TheMealDB" })).toHaveAttribute(
      "href",
      "https://www.themealdb.com",
    );
    const original = screen.getByRole("link", { name: "bbcgoodfood.com" });
    expect(original).toHaveAttribute("href", "https://www.bbcgoodfood.com/recipes/shakshuka");
    expect(original).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("says when no allergens were found, and doesn't link unsafe sources", async () => {
    mockApi({
      "GET /recipes/5": json(
        makeRecipe({
          id: 5,
          allergens: [],
          allergens_complete: true,
          suitable_for: [],
          image_url: null,
          source: "curated",
          source_url: "javascript:alert(1)",
          servings: 2,
          servings_estimated: false,
          per_serving: null,
        }),
      ),
      "GET /allergens": json(ALLERGENS),
    });
    renderWithClient(<RecipePage id={5} />);

    expect(await screen.findByText("None of the 14 major allergens found.")).toBeInTheDocument();
    expect(screen.queryByText(/May be incomplete/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Suitable for/)).not.toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("Egyptian · Serves 2")).toBeInTheDocument();
    expect(screen.getByText(/Nutrition isn't available/)).toBeInTheDocument();
    expect(screen.getByText("A Larder recipe.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /alert/ })).not.toBeInTheDocument();
  });

  it("handles a missing recipe", async () => {
    mockApi({ "GET /allergens": json(ALLERGENS) });
    renderWithClient(<RecipePage id={999} />);

    expect(await screen.findByText("We couldn't find that recipe.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to your plan" })).toHaveAttribute("href", "/plan");
  });

  it("goes back to where you came from", async () => {
    mockApi({ "GET /recipes/101": json(makeRecipe()), "GET /allergens": json(ALLERGENS) });
    renderWithClient(<RecipePage id={101} />);

    fireEvent.click(await screen.findByRole("button", { name: "Back" }));
    expect(nav.back + nav.push.length).toBe(1);
  });
});
