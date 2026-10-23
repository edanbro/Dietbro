import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderWithClient } from "@/test/api";
import { makeRecipe } from "@/test/fixtures";

import { AddToList, itemName, shoppingLines } from "./add-to-list";

vi.mock("@clerk/nextjs", () => ({ useAuth: () => ({ getToken: async () => "t" }) }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

afterEach(() => vi.unstubAllGlobals());

const ing = (name: string, measure: string, grams: number | null, in_pantry = false) => ({
  name,
  measure,
  food_id: grams === null ? null : 1,
  food_name: null,
  grams,
  in_pantry,
});

const STEW = makeRecipe({
  id: 5,
  servings: 4,
  ingredients: [
    ing("onion", "2", 300, true),
    ing("chicken thighs", "800g", 800),
    ing("salt", "a pinch", null),
    ing("water", "500ml", 500),
    ing("paprika", "2 tsp", 6),
  ],
});

describe("shoppingLines", () => {
  it("lists what isn't in the pantry at the servings, the basics unticked", () => {
    const lines = shoppingLines(STEW, 0.5);
    expect(lines.map(itemName)).toEqual([
      "Chicken thighs (400 g)",
      "Salt (a pinch)",
      "Water (250 g)",
      "Paprika (3 g)",
    ]);
    expect(lines.filter((l) => l.basic).map((l) => l.name)).toEqual(["Salt", "Water"]);
    // At the recipe's own servings, amounts as written.
    expect(itemName(shoppingLines(STEW, 1)[0]!)).toBe("Chicken thighs (800g)");
  });
});

describe("AddToList", () => {
  it("adds the ticked ingredients in one go", async () => {
    const sent: unknown[] = [];
    mockApi({
      "POST /shopping/extras/batch": async (req: Request) => {
        const body = (await req.json()) as { names: string[] };
        sent.push(body);
        return Response.json(
          body.names.map((name, i) => ({ id: i + 1, name, checked: false })),
          { status: 201 },
        );
      },
    });
    renderWithClient(<AddToList recipe={STEW} servings={2} />);

    fireEvent.click(screen.getByRole("button", { name: "Add to shopping list" }));
    expect(screen.getByText("1 ingredient is in your pantry already.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Salt/ })).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: /Paprika/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add 1 item" }));

    await waitFor(() => expect(sent).toEqual([{ names: ["Chicken thighs (400 g)"] }]));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add to shopping list" })).toBeInTheDocument(),
    );
  });

  it("hides when everything is in the pantry", () => {
    const stocked = makeRecipe({ ingredients: [ing("onion", "1", 150, true)] });
    const { container } = renderWithClient(<AddToList recipe={stocked} servings={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
